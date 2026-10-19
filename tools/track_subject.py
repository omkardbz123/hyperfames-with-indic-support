"""Auto-reframe: a smoothed crop path that keeps the subject in frame (e.g. 16:9 -> 9:16).

Usage:  uv run tools/track_subject.py <video> [--aspect 9:16] [--start s --end s]
                                      [--render out.mp4] [--debug out.mp4] [--fresh]

Subject per sample (10/s): faces (YuNet) -> people (MediaPipe EfficientDet-Lite0) -> saliency
(OpenCV spectral residual) -> hold. If every face fits in the crop, frame them all; else
follow the largest face, preferring the one nearest the current framing (no jumping between
two people). Smoothing never crosses a cut (shots from tools/analyze_video.py):
  detection dropouts (<= 1.5 s) are bridged from the neighbouring face/person samples, then
  dead-zone (ignore moves < 6 % of the crop width) -> Gaussian (0.25 s) -> pan-speed cap ->
  2 px hysteresis.
Writes analysis/<asset-id>/reframe_<w>x<h>.json: per-frame crop {t, x, y} (top-left, source
px) + crop size; ffmpeg can apply it with --render (sendcmd), HyperFrames via the path JSON.
--debug draws the crop window and detections on the source for review.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import analyze_video as av  # noqa: E402
import assets  # noqa: E402

SAMPLE_FPS = 10.0
DET_W = 640
PERSON_MODEL = cfg.path("cache") / "mediapipe" / "efficientdet_lite0.tflite"
DEADZONE = 0.06      # fraction of crop width
SMOOTH_S = 0.25      # Gaussian sigma (s): no overshoot, so monotone moves stay monotone
GAP_FILL = 1.5       # s: bridge face/person detection dropouts inside a shot
HYST_PX = 2          # final path ignores changes smaller than this (no 1 px dithering)
MAX_PAN = 0.6        # max crop movement per second, fraction of source width


def person_detector():
    if not PERSON_MODEL.exists():
        return None
    from mediapipe.tasks.python import BaseOptions, vision
    return vision.ObjectDetector.create_from_options(vision.ObjectDetectorOptions(
        base_options=BaseOptions(model_asset_path=str(PERSON_MODEL)), category_allowlist=["person"],
        score_threshold=0.45))


def people(det, rgb: np.ndarray) -> list[dict]:
    import mediapipe as mp
    if det is None:
        return []
    h, w = rgb.shape[:2]
    res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    out = []
    for d in res.detections:
        b = d.bounding_box
        # aim at the upper third of a person box (where the head usually is)
        out.append({"x": (b.origin_x + b.width / 2) / w, "y": (b.origin_y + b.height / 3) / h,
                    "w": b.width / w, "h": b.height / h, "score": d.categories[0].score})
    return out


def saliency_x(rgb: np.ndarray) -> float:
    import cv2
    s = cv2.saliency.StaticSaliencySpectralResidual_create()
    ok, m = s.computeSaliency(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        return 0.5
    col = m.sum(0)
    return float((col * np.arange(len(col))).sum() / (col.sum() + 1e-9) / len(col))


def target_x(faces: list[dict], persons: list[dict], prev: float | None, crop_frac: float,
             rgb: np.ndarray) -> tuple[float, str]:
    """Subject centre x (0..1 of source width) and which cue decided it."""
    for kind, objs in (("faces", faces), ("people", persons)):
        if not objs:
            continue
        lo = min(o["x"] - o["w"] / 2 for o in objs)
        hi = max(o["x"] + o["w"] / 2 for o in objs)
        if hi - lo <= crop_frac * 0.9:  # everyone fits: frame the group
            return (lo + hi) / 2, kind
        # follow the biggest, but stay with the one near the current framing if it is comparable
        main = max(objs, key=lambda o: o["w"] * o["h"])
        if prev is not None:
            near = min(objs, key=lambda o: abs(o["x"] - prev))
            if near["w"] * near["h"] >= 0.6 * main["w"] * main["h"]:
                main = near
        return main["x"], kind
    return saliency_x(rgb), "saliency"


def fill_gaps(t: np.ndarray, x: np.ndarray, cue: list[str]) -> np.ndarray:
    """Within one shot, replace lower-priority cues near a face (then person) sample by the
    interpolated face (person) position: detectors drop out for a few frames on dark or
    turned faces, and falling back to saliency would swing the crop away and back."""
    x = x.copy()
    cue = list(cue)
    for kind in ("faces", "people"):
        idx = np.array([i for i, c in enumerate(cue) if c == kind])
        if not len(idx):
            continue
        rank = {"faces": 0, "people": 1, "saliency": 2}
        for i in range(len(x)):
            if rank[cue[i]] <= rank[kind]:
                continue
            near = idx[np.abs(t[idx] - t[i]) <= GAP_FILL]
            if len(near):
                x[i] = np.interp(t[i], t[idx], x[idx])
                cue[i] = kind
    return x


def smooth_segment(x: np.ndarray, fps: float, crop_frac: float) -> np.ndarray:
    from scipy.ndimage import gaussian_filter1d
    if len(x) < 3:
        return x
    # dead-zone: hold until the subject leaves a band around the current framing
    held = x.copy()
    cur = x[0]
    for i, v in enumerate(x):
        if abs(v - cur) > DEADZONE * crop_frac:
            cur = v - np.sign(v - cur) * DEADZONE * crop_frac
        held[i] = cur
    held = gaussian_filter1d(held, SMOOTH_S * fps, mode="nearest")
    # pan-speed cap
    step = MAX_PAN / fps
    out = held.copy()
    for i in range(1, len(out)):
        out[i] = out[i - 1] + np.clip(out[i] - out[i - 1], -step, step)
    return out


def track(path: Path, aspect: str = "9:16", start: float | None = None, end: float | None = None,
          fresh: bool = False, quiet: bool = False) -> dict:
    res = av.analyze(path, quiet=True)
    meta = res["meta"]
    aw, ah = (int(v) for v in aspect.split(":"))
    src_w, src_h = meta["w"], meta["h"]
    crop_h = src_h
    crop_w = int(round(src_h * aw / ah / 2) * 2)
    if crop_w > src_w:  # taller source than target: crop height instead (keep x centred)
        crop_w, crop_h = src_w, int(round(src_w * ah / aw / 2) * 2)
    tag = f"{crop_w}x{crop_h}"
    out_p = assets.analysis_dir(path) / f"reframe_{tag}.json"
    if out_p.exists() and not fresh and start is None and end is None:
        return json.loads(out_p.read_text(encoding="utf-8"))
    t0 = time.time()
    crop_frac = crop_w / src_w
    yun = av.face_detector()
    pdet = person_detector()
    samples = []
    prev = None
    for t, rgb in av.frames(path, DET_W, SAMPLE_FPS, meta):
        if (start is not None and t < start) or (end is not None and t > end):
            continue
        faces = [f for f in av.detect_faces(yun, rgb) if f["w"] > 0.015]
        persons = people(pdet, rgb) if not faces else []
        x, cue = target_x(faces, persons, prev, crop_frac, rgb)
        prev = x
        samples.append({"t": round(t, 3), "x": x, "cue": cue, "faces": faces})
    st = np.array([s["t"] for s in samples])
    xs = np.array([s["x"] for s in samples])
    cuts = [s["start"] for s in res["shots"]] + [meta["duration"] + 1]
    smooth = np.empty_like(xs)
    cue_l = [s["cue"] for s in samples]
    for a, b in zip(cuts[:-1], cuts[1:]):
        m = (st >= a) & (st < b)
        if m.any():
            mi = np.where(m)[0]
            filled = fill_gaps(st[m], xs[m], [cue_l[i] for i in mi])
            smooth[m] = smooth_segment(filled, SAMPLE_FPS, crop_frac)
    # per-frame crop path at the video's frame rate (step interpolation across cuts)
    fps = meta["fps"]
    t_lo = start or 0.0
    t_hi = end if end is not None else meta["duration"]
    ft = np.arange(t_lo, t_hi, 1 / fps)
    seg = np.searchsorted(cuts, ft, side="right") - 1
    fx = np.empty_like(ft)
    for k in np.unique(seg):
        m = seg == k
        sm = (st >= cuts[k]) & (st < cuts[k + 1])
        fx[m] = np.interp(ft[m], st[sm], smooth[sm]) if sm.any() else 0.5
    left = np.clip(np.round(fx * src_w - crop_w / 2), 0, src_w - crop_w).astype(int)
    for i in range(1, len(left)):  # hysteresis, except on cuts
        if seg[i] == seg[i - 1] and abs(left[i] - left[i - 1]) < HYST_PX:
            left[i] = left[i - 1]
    top = int((src_h - crop_h) // 2)
    out = {"asset_id": assets.analysis_dir(path).name, "source": str(path.resolve()), "aspect": aspect,
           "src": [src_w, src_h], "crop": [crop_w, crop_h], "fps": fps,
           "method": "YuNet faces > EfficientDet people > spectral-residual saliency; per shot: gap fill "
                     f"{GAP_FILL}s, dead-zone {DEADZONE}, Gaussian {SMOOTH_S}s, pan cap {MAX_PAN}/s, "
                     f"hysteresis {HYST_PX}px",
           "path": [{"t": round(float(t), 4), "x": int(x), "y": top} for t, x in zip(ft, left)],
           "samples": [{"t": s["t"], "target_x": round(s["x"], 4), "smooth_x": round(float(v), 4), "cue": s["cue"],
                        "faces": s["faces"]} for s, v in zip(samples, smooth)],
           "timings_s": {"total": round(time.time() - t0, 2)}, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if start is None and end is None:
        out_p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    if not quiet:
        cues = {c: sum(1 for s in samples if s["cue"] == c) for c in ("faces", "people", "saliency")}
        print(f"reframe {aspect} ({crop_w}x{crop_h} of {src_w}x{src_h}): {len(out['path'])} frames, cues {cues}, "
              f"{out['timings_s']['total']} s")
    return out


def render(path: Path, rf: dict, out: Path, debug: bool = False) -> Path:
    """Apply the crop path with ffmpeg sendcmd (or draw it over the source with --debug)."""
    cmds = out.with_suffix(".sendcmd.txt")
    t0 = rf["path"][0]["t"]
    lines = []
    last = None
    for p in rf["path"]:
        if p["x"] != last:
            tgt = "drawbox@win" if debug else "crop@c"
            lines.append(f"{p['t'] - t0:.4f} {tgt} x {p['x']};")
            last = p["x"]
    cmds.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cw, ch = rf["crop"]
    x0, y0 = rf["path"][0]["x"], rf["path"][0]["y"]
    rel = cmds.name  # run ffmpeg from the sendcmd folder: avoids escaping a Windows drive colon
    if debug:
        vf = (f"sendcmd=f={rel},drawbox@win=x={x0}:y={y0}:w={cw}:h={ch}:color=yellow@0.9:t=6,"
              f"scale=960:-2")
    else:
        vf = f"sendcmd=f={rel},crop@c=w={cw}:h={ch}:x={x0}:y={y0}"
    dur = rf["path"][-1]["t"] - t0 + 1 / rf["fps"]
    subprocess.run([cfg.ffmpeg(), "-v", "error", "-y", "-ss", f"{t0:.4f}", "-t", f"{dur:.4f}",
                    "-i", str(Path(rf["source"])), "-vf", vf, "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(out.resolve())], check=True, cwd=cmds.parent)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("--render", type=Path, help="write the reframed video here")
    ap.add_argument("--debug", type=Path, help="write a review video with the crop window drawn")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    rf = track(a.file, a.aspect, a.start, a.end, a.fresh)
    if a.render:
        print(f"rendered {render(a.file, rf, a.render)}")
    if a.debug:
        print(f"debug {render(a.file, rf, a.debug, debug=True)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

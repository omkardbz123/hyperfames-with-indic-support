"""Analyse a video once and cache what the edit needs: shots and how good each one is.

Usage:  uv run tools/analyze_video.py <file> [--fresh] [--threshold 3.0] [--quiet]

Writes analysis/<asset-id>/video.json (schema: docs/CONTRACTS.md), per-shot thumbnails in
thumbs/, and sheets/contact.jpg: numbered shot thumbnails with timecodes for Claude to look at.

- meta: ffprobe size, fps, duration, rotation, codecs, HDR flags, audio
- shots: PySceneDetect AdaptiveDetector (hard cuts, robust to fast motion) + ThresholdDetector
  (fades through black); each shot records whether it starts on a "cut" or a "fade"
- per shot: motion (Farneback optical flow, % of frame width per second), camera pan direction,
  sharpness (variance of Laplacian at 640 px), brightness, contrast, colourfulness
  (Hasler-Süsstrunk), faces (OpenCV YuNet: count, largest size, centre), best frame
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

import assets  # noqa: E402

SCHEMA_VERSION = 1
SAMPLE_W = 640          # metrics resolution
SAMPLE_FPS = 4.0        # metric samples per second
FLOW_W = 256            # optical-flow resolution
# YuNet (opencv_zoo, MIT) finds small and mid-distance faces; MediaPipe BlazeFace short-range
# only finds selfie-distance faces (missed both faces in a medium two-shot), so it is the fallback.
YUNET = cfg.path("cache") / "opencv" / "face_detection_yunet_2023mar.onnx"
FACE_MODEL = cfg.path("cache") / "mediapipe" / "blaze_face_short_range.tflite"


def r3(x) -> float:
    return round(float(x), 3)


# --------------------------------------------------------------- probing ---

def probe(path: Path) -> dict:
    out = subprocess.run([cfg.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                          str(path)], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    d = json.loads(out)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        raise SystemExit(f"no video stream in {path}")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    num, den = (int(x) for x in v.get("avg_frame_rate", "0/1").split("/"))
    fps = num / den if den and num else float(eval(v.get("r_frame_rate", "30/1")))  # noqa: S307
    rot = 0
    for sd in v.get("side_data_list", []):
        if "rotation" in sd:
            rot = int(sd["rotation"])
    rot = int(v.get("tags", {}).get("rotate", rot))
    w, h = int(v["width"]), int(v["height"])
    if abs(rot) % 180 == 90:
        w, h = h, w  # display orientation
    transfer = v.get("color_transfer", "")
    return {"w": w, "h": h, "fps": round(fps, 3), "duration": r3(float(d["format"].get("duration", 0))),
            "rotation": rot, "codec": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"),
            "bit_depth": int(v.get("bits_per_raw_sample") or (10 if "10" in (v.get("pix_fmt") or "") else 8)),
            "hdr": transfer in ("smpte2084", "arib-std-b67"), "color_transfer": transfer or None,
            "audio": a is not None, "audio_codec": a.get("codec_name") if a else None,
            "frames": int(v["nb_frames"]) if v.get("nb_frames", "").isdigit() else None}


# ----------------------------------------------------------------- shots ---

def detect_shots(path: Path, threshold: float) -> list[tuple[float, float]]:
    """Hard cuts (AdaptiveDetector) and fades through black (ThresholdDetector), one decode."""
    from scenedetect import AdaptiveDetector, SceneManager, ThresholdDetector, open_video
    video = open_video(str(path))
    sm = SceneManager()
    sm.add_detector(AdaptiveDetector(adaptive_threshold=threshold))
    sm.add_detector(ThresholdDetector(threshold=12, fade_bias=0.0, add_final_scene=False))
    sm.detect_scenes(video, show_progress=False)
    return [(s.seconds, e.seconds) for s, e in sm.get_scene_list()]


def transition_type(path: Path, t: float, fps: float) -> str:
    """'fade' when the frames around a boundary are near black, else 'cut'."""
    lum = [grab(path, max(0.0, t + k / fps), 64).mean() / 255 for k in (-1, 0)]
    return "fade" if max(lum) < 0.06 else "cut"


def frames(path: Path, width: int, fps: float, meta: dict):
    """Yield (t, rgb uint8 HxWx3) at `fps`, scaled to `width` (display orientation)."""
    h = int(round(meta["h"] * width / meta["w"] / 2) * 2)
    cmd = [cfg.ffmpeg(), "-v", "error", "-i", str(path), "-vf", f"fps={fps},scale={width}:{h}",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    n, size = 0, width * h * 3
    while True:
        buf = p.stdout.read(size)
        if len(buf) < size:
            break
        yield n / fps, np.frombuffer(buf, np.uint8).reshape(h, width, 3)
        n += 1
    p.wait()


def fades(lum_t: np.ndarray, lum: np.ndarray) -> list[dict]:
    """Fade to/from black: mean luma below 0.03 for >= 0.25 s."""
    dark = lum < 0.03
    out, i = [], 0
    while i < len(dark):
        if dark[i]:
            j = i
            while j < len(dark) and dark[j]:
                j += 1
            if lum_t[min(j, len(lum_t) - 1)] - lum_t[i] >= 0.25:
                out.append({"start": r3(lum_t[i]), "end": r3(lum_t[min(j, len(lum_t) - 1)]), "kind": "black"})
            i = j
        else:
            i += 1
    return out


# --------------------------------------------------------------- metrics ---

def colourfulness(rgb: np.ndarray) -> float:
    r, g, b = (rgb[..., k].astype(np.float32) for k in range(3))
    rg, yb = r - g, 0.5 * (r + g) - b
    return float(np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))


def face_detector():
    import cv2
    if YUNET.exists():
        return ("yunet", cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.7, 0.3, 50))
    if FACE_MODEL.exists():
        from mediapipe.tasks.python import BaseOptions, vision
        return ("blazeface", vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
            base_options=BaseOptions(model_asset_path=str(FACE_MODEL)), min_detection_confidence=0.6)))
    return None


def detect_faces(det, rgb: np.ndarray) -> list[dict]:
    """Faces as {x, y (centre), w, h} in 0..1 of the frame, plus score."""
    if det is None:
        return []
    kind, d = det
    h, w = rgb.shape[:2]
    boxes = []
    if kind == "yunet":
        import cv2
        d.setInputSize((w, h))
        _, faces = d.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        for f in (faces if faces is not None else []):
            boxes.append((f[0], f[1], f[2], f[3], f[14]))
    else:
        import mediapipe as mp
        res = d.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        for x in res.detections:
            bb = x.bounding_box
            boxes.append((bb.origin_x, bb.origin_y, bb.width, bb.height, x.categories[0].score))
    return [{"x": r3((bx + bw / 2) / w), "y": r3((by + bh / 2) / h), "w": r3(bw / w), "h": r3(bh / h),
             "score": r3(sc)} for bx, by, bw, bh, sc in boxes]


def sample_metrics(path: Path, meta: dict, quiet: bool) -> list[dict]:
    import cv2
    det = face_detector()
    out = []
    prev_small = None
    for t, rgb in frames(path, SAMPLE_W, SAMPLE_FPS, meta):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        small = cv2.resize(gray, (FLOW_W, int(FLOW_W * gray.shape[0] / gray.shape[1])))
        flow_mag, flow_dx, flow_dy = 0.0, 0.0, 0.0
        if prev_small is not None:
            f = cv2.calcOpticalFlowFarneback(prev_small, small, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            mag = np.linalg.norm(f, axis=2)
            # % of frame width per second
            flow_mag = float(np.median(mag) + 0.5 * mag.mean()) / FLOW_W * 100 * SAMPLE_FPS
            flow_dx = float(np.median(f[..., 0])) / FLOW_W * 100 * SAMPLE_FPS
            flow_dy = float(np.median(f[..., 1])) / FLOW_W * 100 * SAMPLE_FPS
        prev_small = small
        out.append({"t": r3(t), "sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1),
                    "brightness": r3(gray.mean() / 255), "contrast": r3(gray.std() / 255),
                    "colourfulness": round(colourfulness(rgb), 1), "motion": round(flow_mag, 2),
                    "pan": [round(flow_dx, 2), round(flow_dy, 2)], "faces": detect_faces(det, rgb)})
    if not quiet:
        print(f"  {len(out)} samples at {SAMPLE_FPS} fps")
    return out


def summarise(shots: list[tuple[float, float]], samples: list[dict]) -> list[dict]:
    st = np.array([s["t"] for s in samples])
    out = []
    for i, (a, b) in enumerate(shots):
        # skip the first sample after a cut: its flow spans the cut
        idx = [k for k in np.where((st >= a + 0.13) & (st < b - 0.01))[0]]
        if not idx:
            idx = [int(np.argmin(np.abs(st - (a + b) / 2)))]
        S = [samples[k] for k in idx]
        faces = [f for s in S for f in s["faces"]]
        face_frames = sum(1 for s in S if s["faces"])
        sharp = np.array([s["sharpness"] for s in S])
        motion = np.array([s["motion"] for s in S[1:]] or [0.0])
        pan = np.array([s["pan"] for s in S[1:]] or [[0.0, 0.0]])
        # best frame: sharp, not too dark, faces help
        score = [s["sharpness"] * (0.4 + min(s["brightness"], 0.6)) * (1.5 if s["faces"] else 1.0) for s in S]
        best = S[int(np.argmax(score))]
        big = max(faces, key=lambda f: f["w"] * f["h"]) if faces else None
        out.append({
            "index": i, "start": r3(a), "end": r3(b), "duration": r3(b - a),
            "motion": round(float(np.mean(motion)), 2), "motion_peak": round(float(np.max(motion)), 2),
            "pan": [round(float(np.median(pan[:, 0])), 2), round(float(np.median(pan[:, 1])), 2)],
            "sharpness": round(float(np.median(sharp)), 1),
            "brightness": r3(np.mean([s["brightness"] for s in S])),
            "contrast": r3(np.mean([s["contrast"] for s in S])),
            "colourfulness": round(float(np.mean([s["colourfulness"] for s in S])), 1),
            "faces": {"present": round(face_frames / len(S), 2),
                      "max_count": max((len(s["faces"]) for s in S), default=0),
                      "largest": big},
            "best_t": best["t"],
        })
    # sharpness is resolution/content dependent: add a 0..1 rank within this video
    if out:
        ranks = np.argsort(np.argsort([s["sharpness"] for s in out]))
        for s, r in zip(out, ranks):
            s["sharpness_rank"] = r3(r / max(len(out) - 1, 1))
    return out


# ---------------------------------------------------------------- sheets ---

def grab(path: Path, t: float, width: int = 640) -> np.ndarray:
    raw = subprocess.run([cfg.ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1",
                          "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                         capture_output=True, check=True).stdout
    import cv2
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def tc(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m):02d}:{s:05.2f}"


def contact_sheet(path: Path, shots: list[dict], out_dir: Path, cols: int = 5) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    (out_dir / "thumbs").mkdir(exist_ok=True)
    (out_dir / "sheets").mkdir(exist_ok=True)
    tiles = []
    for s in shots:
        img = Image.fromarray(grab(path, s["best_t"]))
        img.save(out_dir / "thumbs" / f"shot_{s['index']:03d}.jpg", quality=88)
        s["thumb"] = f"thumbs/shot_{s['index']:03d}.jpg"
        tiles.append(img)
    if not tiles:
        return out_dir / "sheets" / "contact.jpg"
    tw = 384
    th = int(tiles[0].height * tw / tiles[0].width)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 28)), (16, 16, 18))
    try:
        font = ImageFont.truetype(str(cfg.path("fonts") / "inter" / "Inter[opsz,wght].ttf"), 16)
    except OSError:
        font = ImageFont.load_default()
    d = ImageDraw.Draw(sheet)
    for i, (s, img) in enumerate(zip(shots, tiles)):
        x, y = (i % cols) * tw, (i // cols) * (th + 28)
        sheet.paste(img.resize((tw, th)), (x, y))
        face = f" · {s['faces']['max_count']} face" if s["faces"]["max_count"] else ""
        d.text((x + 6, y + th + 4), f"#{s['index']}  {tc(s['start'])}-{tc(s['end'])}  m{s['motion']:.0f}{face}",
               fill=(240, 236, 228), font=font)
    p = out_dir / "sheets" / "contact.jpg"
    sheet.save(p, quality=85)
    return p


# ------------------------------------------------------------------ main ---

def analyze(path: Path, threshold: float = 3.0, fresh: bool = False, quiet: bool = False) -> dict:
    out_dir = assets.analysis_dir(path)
    out_json = out_dir / "video.json"
    if out_json.exists() and not fresh:
        res = json.loads(out_json.read_text(encoding="utf-8"))
        if res.get("schema") == SCHEMA_VERSION:
            if not quiet:
                print(f"cached: {out_json}")
            return res
    t0 = time.time()
    timings = {}
    meta = probe(path)
    if not quiet:
        print(f"analysing {path.name} -> {out_dir.name} ({meta['w']}x{meta['h']} @ {meta['fps']} fps, "
              f"{meta['duration']} s)")
    t = time.time()
    shots = detect_shots(path, threshold)
    if not shots:
        shots = [(0.0, meta["duration"])]
    timings["shots"] = round(time.time() - t, 2)
    t = time.time()
    samples = sample_metrics(path, meta, quiet)
    timings["metrics"] = round(time.time() - t, 2)
    fade_list = fades(np.array([s["t"] for s in samples]), np.array([s["brightness"] for s in samples]))
    shot_list = summarise(shots, samples)
    for s in shot_list:
        s["transition_in"] = transition_type(path, s["start"], meta["fps"]) if s["index"] else None
    t = time.time()
    sheet = contact_sheet(path, shot_list, out_dir)
    timings["sheet"] = round(time.time() - t, 2)
    best = sorted(shot_list, key=lambda s: -s["sharpness_rank"] * (1.5 if s["faces"]["present"] else 1))
    timings["total"] = round(time.time() - t0, 2)
    res = {"schema": SCHEMA_VERSION, "asset_id": out_dir.name, "source": str(path.resolve()), "meta": meta,
           "shot_detector": f"scenedetect AdaptiveDetector(adaptive_threshold={threshold}) + ThresholdDetector(12)",
           "shots": shot_list, "cuts": [s["start"] for s in shot_list[1:]], "fades": fade_list,
           "best_frames": [{"shot": s["index"], "t": s["best_t"]} for s in best[:8]],
           "samples": {"fps": SAMPLE_FPS, "width": SAMPLE_W, "values": samples},
           "contact_sheet": str(sheet.relative_to(out_dir)), "timings_s": timings,
           "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    out_json.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    if not quiet:
        print(f"  {len(shot_list)} shots, {len(fade_list)} fades in {timings['total']} s -> {out_json}")
    return res


def summary(res: dict) -> str:
    m = res["meta"]
    lines = [f"{res['asset_id']}: {m['w']}x{m['h']} {m['fps']} fps {m['duration']} s {m['codec']}"
             f"{' HDR' if m['hdr'] else ''}{' rot ' + str(m['rotation']) if m['rotation'] else ''} | "
             f"{len(res['shots'])} shots | sheet: {res['contact_sheet']}"]
    for s in res["shots"]:
        f = s["faces"]
        lines.append(f"  #{s['index']:<3} {tc(s['start'])}-{tc(s['end'])} ({s['duration']:5.2f}s) motion {s['motion']:5.1f} "
                     f"sharp {s['sharpness_rank']:.2f} bright {s['brightness']:.2f} "
                     f"faces {f['present']:.0%}{' x' + str(f['max_count']) if f['max_count'] else ''}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--threshold", type=float, default=3.0, help="AdaptiveDetector threshold (lower = more cuts)")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if not a.file.exists():
        sys.exit(f"not found: {a.file}")
    print(summary(analyze(a.file, a.threshold, a.fresh, a.quiet)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

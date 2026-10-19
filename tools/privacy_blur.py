"""Blur personal information in a screen recording, frame by frame (follows scrolling).

Usage:  uv run tools/privacy_blur.py <video> --spec blur.json --out media/screen_blurred.mp4 [--sheet]

blur.json:
{
  "anchors": [   // a template cut from one frame; when found, blur boxes RELATIVE to where it is
    {"name": "email_header", "t": 3.5, "box": [503, 468, 762, 498], "blur": "self"},
    {"name": "name_label", "t": 6.0, "box": [505, 327, 677, 352], "blur": [[-5, 73, 455, 115]]}
  ],
  "fixed": [     // plain timed boxes (source px) for things that don't move
    {"box": [490, 78, 1030, 112], "from": 82.0, "to": 95.0}
  ]
}
Anchors should be NON-personal labels next to the personal text (e.g. "Your Full Name"), so a
field is covered even while it is being typed. Matching: normalised cross-correlation on a
half-size grey frame, threshold 0.8 (per anchor "thresh"); a lost anchor is held for 6 frames.
Blur: mosaic + Gaussian, unreadable. Audio is copied. --sheet writes _previews/blur_check.jpg
(frames with the boxes outlined) and prints per-anchor coverage; LOOK at it before using the output.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import cv2  # noqa: E402

HOLD = 6
SCALE = 0.5


def probe(p: Path) -> tuple[int, int, float, float]:
    import fx
    i = fx.probe(p)
    return i["w"], i["h"], i["fps"], i["duration"]


def grab(p: Path, t: float, w: int, h: int) -> np.ndarray:
    raw = subprocess.run([cfg.ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(p), "-frames:v", "1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3)


def blur_region(img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> None:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return
    roi = img[y0:y1, x0:x1]
    small = cv2.resize(roi, (max(1, (x1 - x0) // 14), max(1, (y1 - y0) // 14)), interpolation=cv2.INTER_AREA)
    mosaic = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
    img[y0:y1, x0:x1] = cv2.GaussianBlur(mosaic, (0, 0), 6)


def run(video: Path, spec: dict, out: Path, sheet: bool = False) -> dict:
    W, H, fps, dur = probe(video)
    anchors = []
    for a in spec.get("anchors", []):
        fr = grab(video, a["t"], W, H)
        x0, y0, x1, y1 = a["box"]
        tpl = cv2.cvtColor(fr[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY)
        tpl = cv2.resize(tpl, (max(4, int((x1 - x0) * SCALE)), max(4, int((y1 - y0) * SCALE))), interpolation=cv2.INTER_AREA)
        rel = [[0, 0, x1 - x0, y1 - y0]] if a.get("blur") == "self" else a["blur"]
        pad = a.get("pad", 6)
        anchors.append({**a, "tpl": tpl, "rel": rel, "pad": pad, "last": None, "age": 99, "hits": 0,
                        "thresh": a.get("thresh", 0.8)})
    fixed = spec.get("fixed", [])
    dec = subprocess.Popen([cfg.ffmpeg(), "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    tmp = out.with_name(out.stem + "_v.mp4")
    g = str(int(round(fps)))
    enc = subprocess.Popen([cfg.ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                            "-r", f"{fps}", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "14",
                            "-pix_fmt", "yuv420p", "-g", g, "-keyint_min", g, str(tmp)], stdin=subprocess.PIPE)
    n = 0
    frame_bytes = W * H * 3
    checks = []
    while True:
        buf = dec.stdout.read(frame_bytes)
        if len(buf) < frame_bytes:
            break
        img = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
        t = n / fps
        grey = cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), (int(W * SCALE), int(H * SCALE)), interpolation=cv2.INTER_AREA)
        boxes = []
        for a in anchors:
            if a.get("from") is not None and not (a["from"] <= t <= a.get("to", 1e9)):
                continue
            res = cv2.matchTemplate(grey, a["tpl"], cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if mx >= a["thresh"]:
                a["last"], a["age"] = (int(loc[0] / SCALE), int(loc[1] / SCALE)), 0
                a["hits"] += 1
            else:
                a["age"] += 1
            if a["last"] is not None and a["age"] <= HOLD:
                ax, ay = a["last"]
                for dx0, dy0, dx1, dy1 in a["rel"]:
                    boxes.append((ax + dx0 - a["pad"], ay + dy0 - a["pad"], ax + dx1 + a["pad"], ay + dy1 + a["pad"]))
        for f in fixed:
            if f["from"] <= t <= f["to"]:
                boxes.append(tuple(f["box"]))
        for b in boxes:
            blur_region(img, *b)
        if sheet and n % int(fps * 2) == 0 and boxes:
            vis = img.copy()
            for b in boxes:
                cv2.rectangle(vis, (b[0], b[1]), (b[2], b[3]), (255, 0, 255), 3)
            checks.append((t, cv2.resize(vis, (480, int(480 * H / W)))))
        enc.stdin.write(img.tobytes())
        n += 1
    enc.stdin.close()
    enc.wait()
    dec.wait()
    subprocess.run([cfg.ffmpeg(), "-v", "error", "-y", "-i", str(tmp), "-i", str(video), "-map", "0:v:0", "-map", "1:a:0?",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
    tmp.unlink()
    report = {a["name"]: a["hits"] for a in anchors}
    if sheet and checks:
        cols = 6
        th = checks[0][1].shape[0]
        rows = (len(checks) + cols - 1) // cols
        canvas = np.full((rows * (th + 20), cols * 480, 3), 24, np.uint8)
        for i, (t, im) in enumerate(checks):
            r, c = divmod(i, cols)
            canvas[r * (th + 20): r * (th + 20) + th, c * 480:(c + 1) * 480] = im
            cv2.putText(canvas, f"{int(t // 60):02d}:{t % 60:05.2f}", (c * 480 + 4, r * (th + 20) + th + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1)
        p = cfg.ROOT / "_previews" / "blur_check.jpg"
        cv2.imwrite(str(p), cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR))
        report["sheet"] = str(p)
    report["frames"] = n
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sheet", action="store_true")
    a = ap.parse_args()
    rep = run(a.video, json.loads(a.spec.read_text(encoding="utf-8")), a.out, a.sheet)
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

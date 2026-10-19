"""Stabilisation test with a known synthetic shake.

Usage:  uv run tests/eval_stabilize.py

Takes a near-static 4 s shot of the Tears of Steel excerpt (74.9-79.9 s, a locked-off wide),
adds handheld-style shake (a 1600x666 crop window wobbling up to ~±45 px with mixed 1.3-13 Hz
sines, scaled back to 1920x800), runs tools/fx.py stabilize, and measures frame-to-frame global
motion (phase correlation at 480 px) in the steady original, the shaky clip and the result.
Pass: residual jitter <= 30 % of the shaky clip's.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import cv2  # noqa: E402

import analyze_video as av  # noqa: E402
import fx  # noqa: E402

SRC = ROOT / "tests" / "fixtures" / "footage" / "tos_60-180.mp4"
OUT = ROOT / "tests" / "fixtures" / "fx"


def jitter(path: Path) -> tuple[float, np.ndarray]:
    meta = {"w": 1920, "h": 800}
    prev, d = None, []
    for _, f in av.frames(path, 480, 24, meta):
        g = np.float32(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY))
        if prev is not None:
            (dx, dy), _ = cv2.phaseCorrelate(prev, g)
            d.append((dx, dy))
        prev = g
    d = np.array(d) * (1920 / 480)  # in source pixels
    return float(np.sqrt((d ** 2).sum(1)).mean()), d


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    steady, shaky, stab = OUT / "steady.mp4", OUT / "shaky.mp4", OUT / "stabilized.mp4"
    fx.ff("-ss", "75.2", "-t", "4", "-i", str(SRC), "-an", *fx.ENC, str(steady))
    sx = "160+28*sin(2*PI*1.3*t)+12*sin(2*PI*5.1*t+1)+5*sin(2*PI*13*t+2)"
    sy = "67+18*sin(2*PI*1.7*t+0.5)+9*sin(2*PI*6.3*t+2)+4*sin(2*PI*11*t)"
    fx.ff("-i", str(steady), "-vf", f"crop=1600:666:x='{sx}':y='{sy}',scale=1920:800", *fx.ENC, str(shaky))
    r = fx.stabilize(shaky, stab, smoothing=30)
    j0, _ = jitter(steady)
    j1, _ = jitter(shaky)
    j2, _ = jitter(stab)
    print(f"mean frame-to-frame motion (source px): steady original {j0:.2f} | shaky {j1:.2f} | "
          f"stabilized {j2:.2f}  ({j2 / j1:.0%} of shaky; {r['seconds']} s)")
    fx.ff("-i", str(shaky), "-i", str(stab), "-filter_complex",
          "[0:v]scale=480:-2[a];[1:v]scale=480:-2[b];[a][b]hstack,fps=2,tile=1x6", "-frames:v", "1",
          str(ROOT / "_previews" / "stabilize_compare.jpg"))
    ok = j2 <= 0.3 * j1
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Hold-out test for 4x slow motion: rebuild dropped frames and compare with the real ones.

Usage:  uv run tests/eval_slowmo.py [--start 100.0] [--models rife-v4.6,rife-v4.22,rife-v4.26]

Takes 2 s (48 frames) of moving footage from the Tears of Steel excerpt at 960 px, keeps every
4th frame (12), interpolates 4x back to 45 frames, and scores the 33 generated frames against
the real frames they replace (PSNR, SSIM). Baselines: frame duplication (what a plain slow-down
shows) and ffmpeg minterpolate (motion-compensated). Pass: the configured RIFE model beats
duplication by >= 2 dB PSNR and has mean SSIM >= 0.85, and its worst frame SSIM >= 0.7
(no broken frames).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import cv2  # noqa: E402

import fx  # noqa: E402

SRC = ROOT / "tests" / "fixtures" / "footage" / "tos_60-180.mp4"
K = 4


def read(p: Path) -> np.ndarray:
    return cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_COLOR)


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return 99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def ssim(a: np.ndarray, b: np.ndarray) -> float:
    a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float64)
    b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float64)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = cv2.GaussianBlur(a, (11, 11), 1.5), cv2.GaussianBlur(b, (11, 11), 1.5)
    sa = cv2.GaussianBlur(a * a, (11, 11), 1.5) - mu_a ** 2
    sb = cv2.GaussianBlur(b * b, (11, 11), 1.5) - mu_b ** 2
    sab = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + c1) * (2 * sab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (sa + sb + c2))
    return float(m.mean())


def score(pred: list[np.ndarray], truth: list[np.ndarray]) -> tuple[float, float, float]:
    idx = [i for i in range(len(truth)) if i % K]  # generated positions only
    p = [psnr(pred[i], truth[i]) for i in idx]
    s = [ssim(pred[i], truth[i]) for i in idx]
    return float(np.mean(p)), float(np.mean(s)), float(np.min(s))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=float, default=100.0)
    ap.add_argument("--models", default="rife-v4.6,rife-v4.22,rife-v4.26")
    a = ap.parse_args()
    wd = Path(tempfile.mkdtemp(dir=fx.workdir().parent))
    try:
        full, sub = wd / "full", wd / "sub"
        full.mkdir()
        sub.mkdir()
        fx.ff("-ss", f"{a.start}", "-i", str(SRC), "-frames:v", "45", "-vf", "scale=960:-2", "-vsync", "0",
              str(full / "%08d.png"))
        truth = [read(p) for p in sorted(full.glob("*.png"))]
        for j, i in enumerate(range(0, len(truth), K)):
            shutil.copy(full / f"{i + 1:08d}.png", sub / f"{j + 1:08d}.png")
        n_sub = len(list(sub.glob("*.png")))
        target = (n_sub - 1) * K + 1
        rows = []
        dup = [truth[(i // K) * K] for i in range(len(truth))]
        rows.append(("duplicate frames (plain slow-down)",) + score(dup, truth) + (0.0,))
        # ffmpeg minterpolate
        mi = wd / "mi"
        mi.mkdir()
        t0 = time.time()
        fx.ff("-framerate", "6", "-i", str(sub / "%08d.png"), "-vf",
              "minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1", "-vsync", "0",
              str(mi / "%08d.png"))
        pred = [read(p) for p in sorted(mi.glob("*.png"))][:target]
        rows.append(("ffmpeg minterpolate",) + score(pred, truth[:len(pred)]) + (time.time() - t0,))
        for model in a.models.split(","):
            out = wd / model
            out.mkdir()
            t0 = time.time()
            ok, bad = fx.rife_frames(sub, out, n_sub * K, target, model)  # the same guarded call as fx.slowmo
            if not ok:
                print(f"  {model}: bad output after retries: {bad[:3]}")
            pred = [read(p) for p in sorted(out.glob("*.png"))][:target]
            rows.append((f"RIFE {model}",) + score(pred, truth[:len(pred)]) + (time.time() - t0,))
            if model == a.models.split(",")[0]:
                mid = 2 * 1 + 4 * 5  # a generated frame mid-sequence
                cv2.imwrite(str(ROOT / "_previews" / "slowmo_compare.jpg"),
                            np.vstack([np.hstack([dup[mid], pred[mid]]), np.hstack([truth[mid], np.abs(
                                pred[mid].astype(int) - truth[mid].astype(int)).clip(0, 255).astype(np.uint8) * 3])]))
        print(f"{len(truth)} real frames, {n_sub} kept, {target} rebuilt; scored on the {len(truth) - n_sub} generated")
        print(f"{'method':<36}{'PSNR dB':>9}{'SSIM':>8}{'worst SSIM':>12}{'time s':>8}")
        for name, p, s, w, t in rows:
            print(f"{name:<36}{p:>9.2f}{s:>8.3f}{w:>12.3f}{t:>8.1f}")
        cfg_model = cfg.load().get("fx", {}).get("rife_model", "rife-v4.6")
        best = next((r for r in rows if r[0] == f"RIFE {cfg_model}"), rows[2])
        ok = best[1] >= rows[0][1] + 2 and best[2] >= 0.85 and best[3] >= 0.7
        print(f"configured model {cfg_model}: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(wd, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

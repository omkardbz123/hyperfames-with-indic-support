"""Score auto-reframe on the Tears of Steel excerpt (BUILD_PLAN Phase 4: crop follows a face smoothly).

Usage:  uv run tests/eval_reframe.py [--start 56.7 --end 92.9]

Containment: for every sample with a detected face, is the main face (the one the tracker
followed: nearest the crop centre among the large ones) fully inside the crop, and its centre
inside the middle 70 %? Smoothness: within shots, frame-to-frame crop motion — jitter (median
|second difference|), wobble vs. real follow reversals, and the peak pan speed.
Pass: >= 95 % of face samples fully inside, >= 90 % centred; jitter <= 1 px/frame²;
<= 1 wobble (a reversal after a move smaller than 5 % of the crop width) per 10 s of panning.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import analyze_video as av  # noqa: E402
import track_subject as ts  # noqa: E402

SRC = ROOT / "tests" / "fixtures" / "footage" / "tos_60-180.mp4"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=float, default=56.7)
    ap.add_argument("--end", type=float, default=92.9)
    a = ap.parse_args()
    rf = ts.track(SRC, "9:16", a.start, a.end, quiet=True)
    shots = av.analyze(SRC, quiet=True)["shots"]
    src_w = rf["src"][0]
    cw = rf["crop"][0]
    pt = np.array([p["t"] for p in rf["path"]])
    px = np.array([p["x"] for p in rf["path"]], float)
    inside = centred = n = 0
    misses = []
    for s in rf["samples"]:
        big = [f for f in s["faces"] if f["w"] * f["h"] >= 0.5 * max(g["w"] * g["h"] for g in s["faces"])] \
            if s["faces"] else []
        if not big:
            continue
        x0 = px[min(len(px) - 1, int(np.searchsorted(pt, s["t"])))]
        c = x0 + cw / 2
        f = min(big, key=lambda g: abs(g["x"] * src_w - c))
        fl, fr, fc = (f["x"] - f["w"] / 2) * src_w, (f["x"] + f["w"] / 2) * src_w, f["x"] * src_w
        n += 1
        ins = fl >= x0 - 2 and fr <= x0 + cw + 2
        cen = abs(fc - c) <= 0.35 * cw
        inside += ins
        centred += cen
        if not ins:
            misses.append(s["t"])
    cuts = [s["start"] for s in shots]
    seg = np.searchsorted(cuts, pt, side="right")
    jit, wob, follow, peak, pan_s = [], 0, 0, 0.0, 0.0
    for k in np.unique(seg):
        x = px[seg == k]
        if len(x) < 4:
            continue
        d1 = np.diff(x)
        jit += list(np.abs(np.diff(d1)))
        mv = np.where(np.abs(d1) > 0)[0]
        pan_s += len(mv) / rf["fps"]
        peak = max(peak, float(np.abs(d1).max()) * rf["fps"] / src_w)
        if len(mv) < 2:
            continue
        rv = np.where(np.diff(np.sign(d1[mv])) != 0)[0]
        pts = [x[0]] + [x[mv[r] + 1] for r in rv] + [x[-1]]
        exc = np.abs(np.diff(pts))[:-1]  # excursion before each reversal
        wob += int(np.sum(exc < 0.05 * cw))     # back-and-forth smaller than 5 % of the crop
        follow += int(np.sum(exc >= 0.05 * cw))  # the subject really moved, then came back
    jitter = float(np.median(jit)) if jit else 0.0
    wob10 = wob / max(pan_s, 1e-6) * 10
    ok = n and inside / n >= 0.95 and centred / n >= 0.9 and jitter <= 1 and wob10 <= 1
    print(f"face samples {n}: fully inside crop {inside / n:.0%}, centred (middle 70 %) {centred / n:.0%}")
    if misses:
        print(f"  face outside at: {[round(t, 1) for t in misses[:12]]}")
    print(f"smoothness: jitter {jitter:.2f} px/frame², wobble {wob} ({wob10:.1f} per 10 s of panning), "
          f"{follow} follow reversals (subject moved back), {pan_s:.1f} s panning, peak pan {peak:.2f} widths/s")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

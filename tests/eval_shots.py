"""Score shot-cut detection (BUILD_PLAN Phase 4: cuts within ±2 frames).

Usage:  uv run tests/eval_shots.py

1. Real footage: tests/fixtures/footage/tos_60-180.mp4 (Tears of Steel 1:00-3:00, CC BY 3.0).
   Its 19 cuts were verified by eye (before/after frame pairs + 2 fps strips of every shot
   longer than 10 s, 2026-10-19). For each detected cut, the true cut frame is the
   frame-difference spike within ±3 frames.
2. Montage with exact truth: tests/fixtures/footage/montage.mp4, built here from 14 segments
   taken from inside verified shots (frame-exact trims + concat), including a fade to black.
Pass: every true cut found, no extra cuts, all within ±2 frames.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import analyze_video as av  # noqa: E402

FOOT = ROOT / "tests" / "fixtures" / "footage"
SRC = FOOT / "tos_60-180.mp4"
FPS = 24
VERIFIED_CUTS = 19
# (start_s, dur_s) inside verified shots of the excerpt; segment 7 fades out to black,
# segment 8 fades in (a fade-to-black transition, not a hard cut)
SEGMENTS = [(1.0, 2.0), (11.0, 1.5), (15.5, 2.5), (20.0, 1.25), (23.0, 1.5), (27.0, 3.0),
            (33.0, 1.5), (39.0, 2.0), (45.0, 2.5), (62.0, 3.0), (76.0, 2.0), (80.5, 1.5),
            (94.0, 2.5), (114.0, 3.0)]
FADE_AFTER = 7  # fade out the end of segment index 7 and fade in segment 8 (0.5 s each)


def frame_diffs(path: Path, meta: dict) -> np.ndarray:
    prev, out = None, []
    for _, f in av.frames(path, 160, FPS, meta):
        g = f.astype(np.int16)
        out.append(0.0 if prev is None else float(np.abs(g - prev).mean()))
        prev = g
    return np.array(out)


def build_montage(path: Path) -> list[float]:
    """Exact cut times (s) of the montage; also writes montage.truth.json."""
    parts, filt, cuts, n = [], [], [], 0
    for i, (a, d) in enumerate(SEGMENTS):
        f0, nf = int(round(a * FPS)), int(round(d * FPS))
        chain = f"[0:v]trim=start_frame={f0}:end_frame={f0 + nf},setpts=PTS-STARTPTS,scale=960:400"
        if i == FADE_AFTER:
            chain += f",fade=t=out:start_frame={nf - 12}:nb_frames=12"
        if i == FADE_AFTER + 1:
            chain += ",fade=t=in:start_frame=0:nb_frames=12"
        filt.append(chain + f"[v{i}]")
        parts.append(f"[v{i}]")
        if i:
            cuts.append(n / FPS)
        n += nf
    filt.append("".join(parts) + f"concat=n={len(SEGMENTS)}:v=1:a=0[out]")
    subprocess.run([cfg.ffmpeg(), "-v", "error", "-y", "-i", str(SRC), "-filter_complex", ";".join(filt),
                    "-map", "[out]", "-r", str(FPS), "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
                    str(path)], check=True)
    fade_cut = cuts[FADE_AFTER]
    truth = {"fps": FPS, "hard_cuts": [round(c, 4) for c in cuts if c != fade_cut],
             "fade": {"black_at": round(fade_cut, 4), "kind": "fade out 0.5 s + fade in 0.5 s"},
             "source": "tos_60-180.mp4", "segments": SEGMENTS}
    path.with_suffix(".truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    return cuts


def match(det: list[float], truth: list[float], tol_frames: int = 2) -> tuple[list[float], int, int]:
    errs, used = [], set()
    for t in truth:
        cand = [(abs(d - t), j) for j, d in enumerate(det) if j not in used and abs(d - t) <= 0.5]
        if cand:
            e, j = min(cand)
            used.add(j)
            errs.append((det[j] - t) * FPS)
    return errs, len(truth) - len(errs), len(det) - len(used)


def main() -> int:
    ok = True
    # 1. real footage, spike-verified
    res = av.analyze(SRC, fresh=True, quiet=True)
    det = [x["start"] for x in res["shots"][1:] if x.get("transition_in") == "cut"]
    d = frame_diffs(SRC, res["meta"])
    errs = []
    for c in det:
        k = int(round(c * FPS))
        lo, hi = max(1, k - 3), min(len(d), k + 4)
        spike = lo + int(np.argmax(d[lo:hi]))
        errs.append(k - spike)
    within = all(abs(e) <= 2 for e in errs)
    count_ok = len(det) == VERIFIED_CUTS
    ok &= within and count_ok
    print(f"{'PASS' if within and count_ok else 'FAIL'}  Tears of Steel excerpt: {len(det)} cuts "
          f"(verified {VERIFIED_CUTS}); frame error vs diff spike: {sorted(set(errs))}")
    # 2. montage with exact truth
    mont = FOOT / "montage.mp4"
    cuts = build_montage(mont)
    mres = av.analyze(mont, fresh=True, quiet=True)
    truth = json.loads(mont.with_suffix(".truth.json").read_text(encoding="utf-8"))
    hard = truth["hard_cuts"]
    mdet = [x["start"] for x in mres["shots"][1:] if x.get("transition_in") == "cut"]
    errs, missed, extra = match(mdet, hard)
    m_ok = missed == 0 and extra == 0 and all(abs(e) <= 2 for e in errs)
    ok &= m_ok
    print(f"{'PASS' if m_ok else 'FAIL'}  montage: {len(hard)} hard cuts, detected {len(mdet)} "
          f"(missed {missed}, extra {extra}); frame errors {sorted(round(e, 2) for e in errs)}")
    fb = truth["fade"]["black_at"]
    fade_b = [x for x in mres["shots"] if x.get("transition_in") == "fade" and abs(x["start"] - fb) <= 0.25]
    f_ok = len(fade_b) == 1
    ok &= f_ok
    print(f"{'PASS' if f_ok else 'FAIL'}  fade through black at {fb:.3f} s: "
          f"{[(x['start'], x['transition_in']) for x in fade_b] or 'not found'}")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

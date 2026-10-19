"""Measure caption sync in projects/_test-captions/renders/captions.mp4 (from make_caption_test.py).

Usage:  uv run tests/eval_caption_sync.py [--project projects/_test-captions]

1. Render timing: the 48 px sync marker flips colour at every aligned word start. Each flip's
   frame time vs the word start must be within one frame (+0..33 ms at 30 fps).
2. Audio placement: the MP4's audio is cross-correlated with the fixture to find its offset.
3. End to end: the fixture's word starts are exact, so voice onset in the MP4 = truth + offset.
   Marker flip (caption highlight) vs voice onset must be within ±80 ms for >= 90 % of words
   (BUILD_PLAN Phase 3 acceptance 3).
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

import audiolib as al  # noqa: E402

PROJ = ROOT / "projects" / "_test-captions"
FPS = 30


def marker_flips(mp4: Path) -> np.ndarray:
    raw = subprocess.run([cfg.ffmpeg(), "-v", "error", "-i", str(mp4), "-vf", "crop=24:24:12:12,scale=1:1",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    px = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(int)
    state = np.where(px.sum(1) < 150, 0, np.where((px[:, 0] > 180) & (px[:, 1] < 90), 2, 1))  # black/white/red
    return np.array([i / FPS for i in range(1, len(state)) if state[i] != state[i - 1]])


def audio_offset(mp4: Path, ref_wav: Path) -> float:
    """Lag (s) of the fixture audio inside the MP4's audio track, by cross-correlation."""
    from scipy.signal import correlate
    sr = 8000
    x = al.decode_mono(mp4, sr)
    r = al.decode_mono(ref_wav, sr)
    n = min(len(x), len(r))
    c = correlate(x[:n], r[:n], mode="full", method="fft")
    return (int(np.argmax(c)) - (n - 1)) / sr


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, default=PROJ, help="a test project with sync_words.json")
    a = ap.parse_args()
    proj = a.project if a.project.is_absolute() else ROOT / a.project
    mp4 = proj / "renders" / "captions.mp4"
    meta = json.loads((proj / "sync_words.json").read_text(encoding="utf-8"))
    starts = np.array([w["start"] for w in meta["words"]])
    flips = marker_flips(mp4)
    truth = np.array([w["start"] for w in meta["truth"]])
    ref = proj / meta["reference"] if "reference" in meta else ROOT / "tests" / "fixtures" / f"{meta['fixture']}.wav"
    lag = audio_offset(mp4, ref)
    voice = truth + lag  # exact word onsets as heard in the MP4
    ok = True
    print(f"{len(starts)} words, {len(flips)} marker flips; MP4 audio vs fixture offset {lag * 1000:+.1f} ms")
    if len(flips) != len(starts):
        print("FAIL  marker flip count != word count")
        return 1
    d_render = (flips - starts) * 1000
    r_ok = bool(np.all((d_render >= -1) & (d_render <= 1000 / FPS + 1)))
    ok &= r_ok
    print(f"{'PASS' if r_ok else 'FAIL'}  render timing: flip - word start  min {d_render.min():+.0f} ms, "
          f"max {d_render.max():+.0f} ms  (one frame = {1000 / FPS:.0f} ms)")
    a_ok = abs(lag) <= 0.010
    ok &= a_ok
    print(f"{'PASS' if a_ok else 'FAIL'}  audio placement in the MP4: {lag * 1000:+.1f} ms (<= 10 ms)")
    d_av = (flips - voice) * 1000
    within = float(np.mean(np.abs(d_av) <= 80))
    e_ok = within >= 0.9
    ok &= e_ok
    print(f"{'PASS' if e_ok else 'FAIL'}  caption highlight vs voice onset: median {np.median(d_av):+.0f} ms, "
          f"max |Δ| {np.abs(d_av).max():.0f} ms, {within:.0%} within ±80 ms")
    print("      per word (ms): " + " ".join(f"{x:+.0f}" for x in d_av))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

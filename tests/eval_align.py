"""Score word timings against the speech fixtures.

Usage:  uv run tests/eval_align.py [--engine mms|parakeet] [--set words|speech] [--only words_mr,...]

  --set words  (default): words_<lang> fixtures, exact timings -> timing accuracy
  --set speech : speech_<lang>_<f|m> natural sentences; edge-tts timings are approximate
                 (±100 ms), so use this set for WER, not timing

  mms      : forced-align the known text with tools/align.py (all languages)
  parakeet : HyperFrames Parakeet ASR word timings (English only); also reports WER

Per clip: median / 90th-percentile |start error| and the share of word starts within ±80 ms
(the caption-sync tolerance). Pass: >= 90 % of starts within 80 ms on every clip.
"""
from __future__ import annotations

import argparse
import json
import re
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

FX = ROOT / "tests" / "fixtures"


def norm(w: str) -> str:
    return re.sub(r"[^\w]", "", w.lower())


def wer(ref: list[str], hyp: list[str]) -> float:
    r, h = [norm(x) for x in ref], [norm(x) for x in hyp]
    d = np.zeros((len(r) + 1, len(h) + 1), int)
    d[:, 0], d[0, :] = range(len(r) + 1), range(len(h) + 1)
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i, j] = min(d[i - 1, j] + 1, d[i, j - 1] + 1, d[i - 1, j - 1] + (r[i - 1] != h[j - 1]))
    return d[-1, -1] / max(len(r), 1)


def parakeet_words(wav: Path) -> list[dict]:
    import hf
    with tempfile.TemporaryDirectory(dir=ROOT / "cache") as td:
        subprocess.run(hf.hf_cmd() + ["transcribe", str(wav), "--engine", "parakeet", "-d", td, "--json"],
                       env=hf.hf_env(), capture_output=True, check=True)
        return json.loads((Path(td) / "transcript.json").read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--engine", default="mms", choices=["mms", "parakeet"])
    ap.add_argument("--set", default="words", choices=["words", "speech"])
    ap.add_argument("--only", help="comma list of fixture names, e.g. words_mr,speech_en_m")
    a = ap.parse_args()
    clips = sorted(FX.glob(f"{a.set}_*.truth.json"))
    if a.only:
        keep = set(a.only.split(","))
        clips = [c for c in clips if c.name.split(".")[0] in keep]
    if a.engine == "parakeet":
        clips = [c for c in clips if "_en" in c.name]
    ok = True
    print(f"{'clip':<16}{'words':>6}{'WER':>7}{'med|Δ|':>9}{'p90|Δ|':>9}{'≤80ms':>8}{'Δend med':>10}{'time':>7}")
    for tp in clips:
        truth = json.loads(tp.read_text(encoding="utf-8"))
        wav = tp.with_name(tp.name.replace(".truth.json", ".wav"))
        t0 = time.time()
        if a.engine == "mms":
            import align
            words = align.align(wav, truth["text"], truth["language"])
        else:
            words = parakeet_words(wav)
        dt = time.time() - t0
        ref = truth["words"]
        w = wer([x["text"] for x in ref], [x["text"] for x in words])
        # pair words by order when counts match, else by normalised text in sequence
        pairs = []
        if len(words) == len(ref):
            pairs = list(zip(ref, words))
        else:
            j = 0
            for r in ref:
                for k in range(j, min(j + 3, len(words))):
                    if norm(words[k]["text"]) == norm(r["text"]):
                        pairs.append((r, words[k]))
                        j = k + 1
                        break
        ds = np.array([abs(h["start"] - r["start"]) for r, h in pairs]) * 1000
        de = np.array([abs(h["end"] - r["end"]) for r, h in pairs]) * 1000
        within = float(np.mean(ds <= 80)) if len(ds) else 0.0
        ok &= within >= 0.9
        print(f"{tp.name.split('.')[0]:<16}{len(ref):>6}{w:>7.1%}{np.median(ds):>8.0f}m{np.percentile(ds, 90):>8.0f}m"
              f"{within:>8.0%}{np.median(de):>9.0f}m{dt:>6.1f}s")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

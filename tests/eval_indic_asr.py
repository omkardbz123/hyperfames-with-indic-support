"""WER / CER of Indic-Transcribe on the edge-tts fixtures (BUILD_PLAN Phase 3 acceptance 1).

Usage:  uv run tests/eval_indic_asr.py [--device ov-cpu] [--sets speech,words] [--mode native]

Normalisation before scoring: punctuation (. , ! ? । ॥ " ') removed, whitespace collapsed,
lower-cased (English). CER is on characters without spaces. Pass: mean WER < 10 % over the
Marathi and Hindi speech clips.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import indic_asr as I  # noqa: E402

FX = ROOT / "tests" / "fixtures"


def norm(s: str) -> list[str]:
    s = re.sub(r"[.,!?।॥\"'“”‘’:;()\-]", " ", s.lower())
    return s.split()


def edit(a: list, b: list) -> int:
    d = np.arange(len(b) + 1)
    for i in range(1, len(a) + 1):
        prev, d[0] = d.copy(), i
        for j in range(1, len(b) + 1):
            d[j] = min(prev[j] + 1, d[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
    return int(d[-1])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", help="ov-cpu | ov-gpu | official")
    ap.add_argument("--weights", help="int8 | fp16")
    ap.add_argument("--model", choices=["core", "flex"])
    ap.add_argument("--sets", default="speech")
    ap.add_argument("--mode", default="native")
    a = ap.parse_args()
    asr = I.IndicASR(a.device, a.weights, a.model, a.mode)
    rows, indic_wer = [], []
    for s in a.sets.split(","):
        for tp in sorted(FX.glob(f"{s}_*.truth.json")):
            t = json.loads(tp.read_text(encoding="utf-8"))
            wav = I.load_audio(tp.with_name(tp.name.replace(".truth.json", ".wav")))
            t0 = time.time()
            r = asr.transcribe(wav, t["language"], a.mode)
            ref, hyp = norm(t["text"]), norm(r["text"])
            wer = edit(ref, hyp) / len(ref)
            cer = edit(list("".join(ref)), list("".join(hyp))) / len("".join(ref))
            if t["language"] in ("mr", "hi") and s == "speech":
                indic_wer.append(wer)
            rows.append((tp.name.split(".")[0], wer, cer, time.time() - t0, len(wav) / 16000, r["text"]))
    print(f"model {asr.model}, device {asr.device}, mode {a.mode}")
    for name, wer, cer, dt, dur, text in rows:
        print(f"{name:<14} WER {wer:6.1%}  CER {cer:6.1%}  {dt:5.1f} s for {dur:4.1f} s  | {text[:110]}")
    if indic_wer:
        m = float(np.mean(indic_wer))
        print(f"mean WER over Marathi + Hindi speech clips: {m:.1%}  ->  {'PASS' if m < 0.10 else 'FAIL'} (< 10 %)")
        return 0 if m < 0.10 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

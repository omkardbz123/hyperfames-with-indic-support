"""Forced-align a known text (script, lyrics or an ASR transcript) to audio: word timings.

Usage:  uv run tools/align.py <audio> --text "..." | --text-file lyrics.txt  --lang mr|hi|en
                              [--out words.json]

MMS-300m forced aligner (ctc-forced-aligner; model MahmoudAshraf/mms-300m-1130-forced-aligner,
CC BY-NC 4.0: fine for this non-commercial studio, credit it). Devanagari is romanised with
uroman before alignment. For songs, align on the vocal stem (tools/separate.py --quality).
Digits are handled: English/Latin ones are aligned as their spoken English form, pure numbers in
mr/hi as a wildcard between their neighbours (see spoken_form).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()
cfg.model_cache_env()

import audiolib as al  # noqa: E402

ISO3 = {"mr": "mar", "hi": "hin", "en": "eng", "mar": "mar", "hin": "hin", "eng": "eng"}
MODEL = "MahmoudAshraf/mms-300m-1130-forced-aligner"
_model = None


def _load():
    global _model
    if _model is None:
        import torch
        from ctc_forced_aligner import load_alignment_model
        _model = load_alignment_model("cpu", MODEL, dtype=torch.float32)
    return _model


_DIGITS = re.compile(r"\d+")


def spoken_form(word: str, lang: str) -> str:
    """What to align for a word. The aligner's vocabulary has no digits ("2026" became an empty
    token, "E20" just "e"), so digits in English or Latin-script words are spelled out in English
    and glued into one word ("E20" -> "etwenty"). Pure numbers in Marathi/Hindi speech stay as
    they are and become a wildcard in _run (they may be spoken in either language)."""
    if not any(ch.isdigit() for ch in word):
        return word
    if lang == "en" or re.search(r"[A-Za-z]", word):
        from num2words import num2words
        return _DIGITS.sub(lambda m: re.sub(r"[^a-z]", "", num2words(int(m.group()), lang="en")), word)
    return word


def _run(emissions, stride, tokenizer, words: list[str], lang: str, star: str) -> list[dict]:
    from ctc_forced_aligner import get_alignments, get_spans, postprocess_results, preprocess_text
    spoken = " ".join(spoken_form(w, lang) for w in words)
    tokens_starred, text_starred = preprocess_text(spoken, romanize=True, language=ISO3[lang], star_frequency=star)
    # a word that romanises to nothing (digits, symbols) aligns as <star>: it absorbs whatever
    # audio lies between its neighbours instead of breaking the alignment
    tokens_starred = [t if t.strip() else "<star>" for t in tokens_starred]
    # show the original words, not their spoken forms (same order, one entry per word)
    it = iter(words)
    text_starred = [t if t == "<star>" else next(it) for t in text_starred]
    segments, scores, blank = get_alignments(emissions, tokens_starred, tokenizer)
    spans = get_spans(tokens_starred, segments, blank)
    return postprocess_results(text_starred, spans, stride, scores)


def align(audio: str | Path, text: str, lang: str, waveform=None) -> list[dict]:
    """Return [{text, start, end, conf}] for every whitespace-separated word of `text`.

    Two alignments share one set of emissions: a <star> token between every word gives the
    most accurate starts (silence goes to the star), stars only at the edges give the most
    accurate ends. Each gets the bias correction measured on the exact-timing fixtures
    ([align] in config/studio.toml); then times are made monotonic.
    """
    import torch
    from ctc_forced_aligner import generate_emissions
    model, tokenizer = _load()
    if waveform is None:
        waveform = al.decode_mono(audio, 16000)
    wav = torch.from_numpy(waveform).to(model.dtype)
    emissions, stride = generate_emissions(model, wav, batch_size=4)
    words = text.split()
    seg = _run(emissions, stride, tokenizer, words, lang, "segment")
    edg = _run(emissions, stride, tokenizer, words, lang, "edges")
    c = cfg.load().get("align", {})
    s_off, e_off = float(c.get("start_offset", 0.0)), float(c.get("end_offset", 0.0))
    dur = len(waveform) / 16000
    out = []
    for a, b in zip(seg, edg):
        start = max(0.0, a["start"] + s_off)
        end = min(dur, max(b["end"] + e_off, start + 0.05))
        sc = (a["score"] + b["score"]) / 2
        out.append({"text": a["text"], "start": start, "end": end,
                    "conf": math.exp(sc) if sc < 0 else sc})
    for w, word in zip(out, words):  # wildcard-aligned words (numbers in mr/hi): timing is a guess
        if not re.search(r"[^\W\d_]", spoken_form(word, lang)):
            w["conf"] = 0.0
    for i in range(len(out) - 1):  # no overlaps; keep every word at least 50 ms long
        if out[i]["end"] > out[i + 1]["start"]:
            out[i]["end"] = max(out[i]["start"] + 0.05, out[i + 1]["start"])
            out[i + 1]["start"] = max(out[i + 1]["start"], out[i]["end"])
    return [{"text": w["text"], "start": round(w["start"], 3), "end": round(w["end"], 3),
             "conf": round(w["conf"], 3)} for w in out]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--text-file", type=Path)
    ap.add_argument("--lang", required=True, choices=["mr", "hi", "en"])
    ap.add_argument("--out", type=Path, help="write words JSON here (default: print)")
    a = ap.parse_args()
    text = a.text if a.text is not None else a.text_file.read_text(encoding="utf-8")
    t0 = time.time()
    words = align(a.audio, text, a.lang)
    out = json.dumps(words, indent=1, ensure_ascii=False)
    if a.out:
        a.out.write_text(out, encoding="utf-8")
        print(f"{len(words)} words aligned in {time.time() - t0:.1f} s -> {a.out}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

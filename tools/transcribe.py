"""Transcribe speech or align a known script/lyrics: word timings + caption cues.

Usage:  uv run tools/transcribe.py <audio|video> --lang mr|hi|en
                                   [--text-file script.txt | --text "..."]   (align, no ASR)
                                   [--engine auto|indic|parakeet] [--mode native|mixed|romanised]
                                   [--vocals] [--no-realign]
                                   [--hf projects/<slug>/transcript.json] [--fresh]

Writes analysis/<asset-id>/transcript.json (docs/CONTRACTS.md) + transcript.srt / .vtt.

Routes
  script/lyrics given  -> MMS forced alignment of that exact text (best: the user's own words)
  en                   -> Parakeet TDT 0.6B v3 (HyperFrames, on-device), then MMS re-timing
  mr / hi              -> Indic-Transcribe-core (tools/indic_asr.py, OpenVINO int8), then MMS
                          alignment (the model gives no word timestamps)
  --vocals             -> work on the BS-RoFormer vocal stem (songs / music under speech)
Words with alignment conf < 0.05 (~bottom 5 % on real speech) are flagged `low_conf` for review.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()
cfg.model_cache_env()

import assets  # noqa: E402
import audiolib as al  # noqa: E402
import captions  # noqa: E402

SCHEMA_VERSION = 1
LOW_CONF = 0.05  # MMS alignment confidence; real conversational Marathi: median 0.52, 5th pct 0.035


class NeedsUser(RuntimeError):
    """A ⛔ USER step is required before this route can run."""


def parakeet(path: Path) -> list[dict]:
    import hf
    with tempfile.TemporaryDirectory(dir=cfg.path("cache")) as td:
        p = subprocess.run(hf.hf_cmd() + ["transcribe", str(path), "--engine", "parakeet", "-d", td, "--json"],
                           env=hf.hf_env(), capture_output=True, text=True, encoding="utf-8", errors="replace")
        f = Path(td) / "transcript.json"
        if p.returncode or not f.exists():
            raise RuntimeError(f"hyperframes transcribe failed: {p.stderr[-500:]}")
        return [{"text": w["text"], "start": w["start"], "end": w["end"]}
                for w in json.loads(f.read_text(encoding="utf-8"))]


def indic(path: Path, lang: str, mode: str = "native") -> dict:
    """Indic-Transcribe text (no timestamps) via tools/indic_asr.py (OpenVINO int8)."""
    import indic_asr
    want = cfg.load().get("indic_asr", {}).get("model_native" if mode == "native" else "model_mixed", "flex")
    if not (indic_asr.ov_dir("int8", want) / "decoder.xml").exists() and not (indic_asr.src_dir(want) / "model.safetensors").exists():
        raise NeedsUser(
            f"Marathi/Hindi transcription needs Indic-Transcribe-{want.title()} (OpenVINO int8), a gated model:\n"
            "  1. Sign in at huggingface.co and accept the licence on\n"
            "     https://huggingface.co/omkar9896/indic-transcribe-openvino-int8\n"
            "  2. In a terminal in this folder run:  uv run hf auth login   (paste a read token)\n"
            "  3. uv run tools/setup.py --only indic   (downloads the model, ~1.2 GB)\n"
            "Meanwhile, pass the script/lyrics with --text-file to align it instead.")
    return indic_asr.IndicASR(mode=mode).transcribe(indic_asr.load_audio(path), lang, mode)


def transcribe(path: Path, lang: str, text: str | None = None, engine: str = "auto", vocals: bool = False,
               realign: bool = True, fresh: bool = False, quiet: bool = False, mode: str = "native") -> dict:
    out_dir = assets.analysis_dir(path)
    key = f"{lang}-{'script' if text else engine}{'-vocals' if vocals else ''}{'-' + mode if mode != 'native' else ''}"
    out = out_dir / "transcript.json"
    if out.exists() and not fresh:
        tr = json.loads(out.read_text(encoding="utf-8"))
        if tr.get("schema") == SCHEMA_VERSION and tr.get("key") == key and (not text or tr.get("text") == text):
            if not quiet:
                print(f"cached: {out}")
            return tr
    import align
    t0 = time.time()
    src = path
    if vocals:
        import separate
        src = separate.separate(path, quality=True, quiet=quiet)["vocals"]
    wave = al.decode_mono(src, 16000)
    timings = {}
    if text:
        eng = "mms-align:script"
        words = align.align(src, text, lang, waveform=wave)
    else:
        if engine == "auto":
            engine = "parakeet" if lang == "en" else "indic"
        if engine == "parakeet":
            asr = parakeet(src)
            timings["asr"] = round(time.time() - t0, 2)
            eng = "parakeet-tdt-0.6b-v3"
            if realign and asr:
                t1 = time.time()
                words = align.align(src, " ".join(w["text"] for w in asr), lang, waveform=wave)
                timings["align"] = round(time.time() - t1, 2)
                eng += "+mms-align"
            else:
                words = asr
        elif engine == "indic":
            r = indic(src, lang, mode)
            timings["asr"] = round(time.time() - t0, 2)
            eng = f"indic-transcribe-{r['model']}[{r['device']}]+mms-align"
            t1 = time.time()
            words = align.align(src, r["text"], lang, waveform=wave) if r["text"] else []
            timings["align"] = round(time.time() - t1, 2)
        else:
            raise SystemExit(f"unknown engine {engine}")
    for w in words:
        if w.get("conf") is not None and w["conf"] < LOW_CONF:
            w["low_conf"] = True
    cues = captions.build_cues(words)
    timings["total"] = round(time.time() - t0, 2)
    dur = len(wave) / 16000
    tr = {"schema": SCHEMA_VERSION, "asset_id": out_dir.name, "source": str(path.resolve()),
          "key": key, "language": lang, "engine": eng, "audio": "vocal stem" if vocals else "mix",
          "duration": round(dur, 3), "text": text, "words": words, "cues": cues,
          "low_conf_words": [w["text"] for w in words if w.get("low_conf")],
          "timings_s": timings, "rtf": round(timings["total"] / max(dur, 1e-6), 3),
          "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    out.write_text(json.dumps(tr, indent=1, ensure_ascii=False), encoding="utf-8")
    captions.write_exports(tr, out_dir / "transcript.srt", out_dir / "transcript.vtt")
    if not quiet:
        print(f"{eng}: {len(words)} words, {len(cues)} cues in {timings['total']} s -> {out}")
    return tr


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--lang", required=True, choices=["mr", "hi", "en"])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--text")
    g.add_argument("--text-file", type=Path)
    ap.add_argument("--engine", default="auto", choices=["auto", "indic", "parakeet"])
    ap.add_argument("--mode", default="native", choices=["native", "mixed", "romanised"],
                    help="mr/hi output script: native Devanagari (default), mixed = English words and "
                         "numbers stay in Latin script / digits, romanised = everything in Latin")
    ap.add_argument("--vocals", action="store_true", help="use the BS-RoFormer vocal stem (songs)")
    ap.add_argument("--no-realign", action="store_true", help="keep ASR timings (skip MMS re-timing)")
    ap.add_argument("--hf", type=Path, help="also write a HyperFrames project transcript.json here")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    if not a.file.exists():
        sys.exit(f"not found: {a.file}")
    text = a.text if a.text is not None else (a.text_file.read_text(encoding="utf-8") if a.text_file else None)
    try:
        tr = transcribe(a.file, a.lang, text, a.engine, a.vocals, not a.no_realign, a.fresh, mode=a.mode)
    except NeedsUser as e:
        print(f"⛔ USER step needed:\n{e}")
        return 2
    if a.hf:
        captions.write_exports(tr, hf=a.hf)
        print(f"HyperFrames transcript -> {a.hf}")
    for c in tr["cues"][:6]:
        print(f"  {c['start']:7.3f}-{c['end']:7.3f}  {c['text']}")
    if tr["low_conf_words"]:
        print(f"  review (low confidence): {', '.join(tr['low_conf_words'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

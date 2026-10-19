"""Voiceover: one clip per script line, with accurate word timings (ported from the Goa reel).

Usage:  uv run tools/voiceover.py <script.json> --out projects/<slug>/assets/vo [--fresh]
        uv run tools/voiceover.py --say "text" --lang mr [--voice mr_f] --out DIR   (one line)

script.json:
  {"lang": "mr", "voice": "mr_f", "rate": "+0%", "pitch": "+0Hz",
   "lines": [{"id": "l01", "text": "..."}, {"id": "l02", "text": "...", "voice": "mr_m", "rate": "-5%"}]}
Voices ([voice] in config/studio.toml): mr_f/mr_m/hi_f/hi_m/en_f/en_m = edge-tts Microsoft
neural voices (online, free); kokoro_en_f/kokoro_en_m/kokoro_hi_f = Kokoro-82M (offline, via
`hyperframes tts`; no Marathi). A full voice id (e.g. "mr-IN-ManoharNeural", "af_heart") works too.

Per line -> <out>/<id>.wav (48 kHz mono, lead/trailing silence trimmed to 40 ms) and <id>.json
{text, lang, voice, duration, words:[{text,start,end,conf}]}. Word timings come from the MMS
aligner on the generated audio (edge-tts WordBoundary is off by up to ~100 ms). <out>/vo.json
lists every line. Lines are cached by (text, voice, rate, pitch): re-runs only redo changes.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import audiolib as al  # noqa: E402

SR = 48000
DEFAULT_VOICES = {"mr_f": "mr-IN-AarohiNeural", "mr_m": "mr-IN-ManoharNeural",
                  "hi_f": "hi-IN-SwaraNeural", "hi_m": "hi-IN-MadhurNeural",
                  "en_f": "en-IN-NeerjaExpressiveNeural", "en_m": "en-IN-PrabhatNeural",
                  "kokoro_en_f": "kokoro:af_heart", "kokoro_en_m": "kokoro:am_michael",
                  "kokoro_hi_f": "kokoro:hf_alpha", "kokoro_hi_m": "kokoro:hm_omega"}


def resolve_voice(v: str) -> str:
    table = {**DEFAULT_VOICES, **cfg.load().get("voice", {})}
    v = table.get(v, v)
    if "-" not in v and not v.startswith("kokoro:") and "_" in v:  # bare Kokoro id like af_heart
        v = "kokoro:" + v
    return v


async def _edge(text: str, voice: str, rate: str, pitch: str, path: Path) -> None:
    import edge_tts
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
    audio = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            audio += chunk["data"]
    if not audio:
        raise RuntimeError("edge-tts returned no audio")
    path.write_bytes(bytes(audio))


def synth(text: str, voice: str, rate: str, pitch: str, lang: str, raw: Path) -> None:
    if voice.startswith("kokoro:"):
        import hf
        speed = 1.0 + float(rate.strip("%+")) / 100 * (1 if not rate.startswith("-") else -1) if rate else 1.0
        p = subprocess.run(hf.hf_cmd() + ["tts", text, "-v", voice.split(":", 1)[1], "-s", f"{speed:.2f}",
                                          "-o", str(raw), "--json"] + (["-l", "hi"] if lang == "hi" else []),
                           env=hf.hf_env(), capture_output=True, text=True, encoding="utf-8")
        if p.returncode or not raw.exists():
            raise RuntimeError(f"kokoro failed: {p.stdout[-300:]} {p.stderr[-300:]}")
        return
    for attempt in range(3):
        try:
            asyncio.run(_edge(text, voice, rate, pitch, raw))
            return
        except Exception as e:  # noqa: BLE001
            if "403" in str(e):
                raise RuntimeError("edge-tts 403: it has gone stale; run `uv add edge-tts --upgrade-package edge-tts`") from e
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def trim(y: np.ndarray, keep: float = 0.04, floor_db: float = -45) -> tuple[np.ndarray, float]:
    """Cut leading/trailing silence (edge-tts adds ~1 s of tail); returns (audio, seconds cut at the head)."""
    hop = int(0.005 * SR)
    n = len(y) // hop
    e = 20 * np.log10(np.sqrt((y[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    live = np.where(e > e.max() + floor_db)[0]
    if not len(live):
        return y, 0.0
    a = max(0, live[0] * hop - int(keep * SR))
    b = min(len(y), (live[-1] + 1) * hop + int(keep * SR))
    return y[a:b], a / SR


def make_line(line: dict, defaults: dict, out: Path, fresh: bool = False) -> dict:
    import align
    lang = line.get("lang", defaults.get("lang", "en"))
    voice = resolve_voice(line.get("voice", defaults.get("voice", f"{lang}_f")))
    rate = line.get("rate", defaults.get("rate", "+0%"))
    pitch = line.get("pitch", defaults.get("pitch", "+0Hz"))
    key = hashlib.sha1(json.dumps([line["text"], voice, rate, pitch], ensure_ascii=False).encode()).hexdigest()[:12]
    wav, meta_p = out / f"{line['id']}.wav", out / f"{line['id']}.json"
    if not fresh and meta_p.exists() and wav.exists():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        if meta.get("key") == key:
            return meta
    raw = out / f"_{line['id']}.raw{'.wav' if voice.startswith('kokoro:') else '.mp3'}"
    synth(line["text"], voice, rate, pitch, lang, raw)
    y, _ = trim(al.decode(raw, SR, 1)[:, 0])
    raw.unlink()
    al.write_wav(wav, y, SR)
    words = align.align(wav, line["text"], lang, waveform=al.decode_mono(wav, 16000))
    meta = {"id": line["id"], "key": key, "text": line["text"], "lang": lang, "voice": voice, "rate": rate,
            "pitch": pitch, "duration": round(len(y) / SR, 3), "words": words,
            "engine": "kokoro-82m" if voice.startswith("kokoro:") else "edge-tts",
            "timing": "mms-align on the generated audio"}
    meta_p.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return meta


def run(script: dict, out: Path, fresh: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    lines = [make_line(l, script, out, fresh) for l in script["lines"]]
    manifest = {"lines": [{k: m[k] for k in ("id", "text", "lang", "voice", "duration", "engine")} | {
        "file": f"{m['id']}.wav", "words": m["words"]} for m in lines],
        "total_duration": round(sum(m["duration"] for m in lines), 3)}
    (out / "vo.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("script", nargs="?", type=Path)
    ap.add_argument("--say", help="speak one line instead of a script file")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--voice")
    ap.add_argument("--rate", default="+0%")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    if a.say:
        script = {"lang": a.lang, "voice": a.voice or f"{a.lang}_f", "rate": a.rate,
                  "lines": [{"id": "line", "text": a.say}]}
    elif a.script:
        script = json.loads(a.script.read_text(encoding="utf-8"))
    else:
        sys.exit("give a script.json or --say")
    t0 = time.time()
    m = run(script, a.out, a.fresh)
    for l in m["lines"]:
        print(f"{l['id']}: {l['duration']:5.2f}s  {l['voice']:<28} {l['text'][:60]}")
    print(f"{len(m['lines'])} lines, {m['total_duration']} s of voice in {time.time() - t0:.1f} s -> {a.out}/vo.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())

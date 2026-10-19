"""Generate synthetic test media with exact ground truth into tests/fixtures/.

Usage:  uv run tools/make_fixtures.py [--only beat|vocalmix|speech|words]

beat_128.wav  + beat_128.truth.json
    40 s, 128 BPM 4/4 drum track, first beat 0.5 s. Sections: intro (hats + pad, quiet) 0-8 s ->
    groove (kick/snare/hats/bass) -> one-bar hard stop 21.125-23.0 s -> drop (everything, loud) 23-40 s.
    Truth: beats, downbeats, kick/snare times, sections, silence, drop.
vocalmix.wav  + vocalmix_vocals.wav + vocalmix_instrumental.wav + vocalmix.truth.json
    beat_128 instrumental with an edge-tts Marathi voice line on top (known stems).
speech_<lang>_<f|m>.wav + .truth.json
    Two edge-tts sentences per language (mr, hi, en-IN), female and male voice, 16 kHz mono,
    with edge-tts WordBoundary word timings. These timings are only approximate (first word
    always reported at 0.100 s; actual onset 0.16-0.21 s; ±100 ms scatter): use for WER only.
words_<lang>.wav + .truth.json
    The same sentences, each word synthesised alone (female voice), trimmed at its energy
    edges (-40 dB) and joined with seeded 80-250 ms gaps: exact word timings for the aligner
    and caption-sync tests.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audiolib as al  # noqa: E402
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

OUT = cfg.ROOT / "tests" / "fixtures"
SR = 44100
BPM = 128.0
T0 = 0.5            # first beat
DUR = 40.0
SPB = 60.0 / BPM
beat_t = lambda i: T0 + i * SPB  # noqa: E731
INTRO_END = beat_t(16)            # 8.0 s, a downbeat
STOP = (beat_t(44), beat_t(48))   # one-bar hard stop 21.125-23.0 s (downbeat to downbeat)
DROP = beat_t(48)                 # 23.0 s, the downbeat after the stop
VO_TEXT = "गोव्यातील प्राणी मुक्ती मोर्चा या रविवारी पणजीत होणार आहे. सर्वांनी नक्की या."
VO_VOICE = "mr-IN-AarohiNeural"
VO_AT = 9.0


def kick(sr=SR):
    n = int(0.35 * sr); t = np.arange(n) / sr
    f = 50 + 110 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 9)


def snare(sr=SR, seed=2):
    n = int(0.22 * sr); t = np.arange(n) / sr
    noise = np.random.default_rng(seed).normal(0, 1, n)
    noise = noise - np.convolve(noise, np.ones(8) / 8, mode="same")  # crude high-pass
    return (0.6 * noise * np.exp(-t * 22) + 0.5 * np.sin(2 * np.pi * 185 * t) * np.exp(-t * 30))


def hat(sr=SR, seed=4):
    n = int(0.06 * sr); t = np.arange(n) / sr
    noise = np.random.default_rng(seed).normal(0, 1, n)
    noise = noise - np.convolve(noise, np.ones(4) / 4, mode="same")
    return noise * np.exp(-t * 70) * 0.5


def tone(freq, length, sr=SR, saw=False):
    t = np.arange(int(length * sr)) / sr
    if saw:
        x = 2 * ((t * freq) % 1.0) - 1
        x = np.convolve(x, np.ones(12) / 12, mode="same")  # soften
    else:
        x = np.sin(2 * np.pi * freq * t)
    env = np.minimum(1, t / 0.01) * np.exp(-t * 2.0)
    return x * env


def add(buf, clip, t, gain=1.0):
    i = int(round(t * SR))
    n = min(len(clip), len(buf) - i)
    if n > 0 and i >= 0:
        buf[i:i + n] += clip[:n] * gain


def make_beat():
    n = int(DUR * SR)
    buf = np.zeros(n)
    spb = 60.0 / BPM
    beats = [T0 + i * spb for i in range(int((DUR - T0) / spb) + 1) if T0 + i * spb < DUR - 0.05]
    in_stop = lambda t: STOP[0] <= t < STOP[1]  # noqa: E731
    truth = {"bpm": BPM, "beats": [], "downbeats": [], "kicks": [], "snares": [], "hihats": [],
             "sections": [{"start": 0.0, "end": INTRO_END, "label": "intro"},
                          {"start": INTRO_END, "end": STOP[0], "label": "groove"},
                          {"start": STOP[0], "end": STOP[1], "label": "break"},
                          {"start": DROP, "end": DUR, "label": "drop"}],
             "silences": [{"start": STOP[0], "end": STOP[1]}], "drops": [DROP]}
    roots = [55.0, 55.0, 43.65, 49.0]  # A1 A1 F1 G1 per bar
    for i, t in enumerate(beats):
        bar, pos = divmod(i, 4)
        truth["beats"].append(round(t, 4))  # the grid continues through the stop
        if pos == 0:
            truth["downbeats"].append(round(t, 4))
        if in_stop(t):
            continue
        loud = 1.6 if t >= DROP else 1.0
        # hats on 8ths everywhere
        for h in (t, t + spb / 2):
            if not in_stop(h):
                add(buf, hat(seed=i), h, 0.25 * loud)
                truth["hihats"].append(round(h, 4))
        if t < INTRO_END:
            if pos == 0:  # quiet pad chord per bar
                for f in (220, 261.6, 329.6):
                    add(buf, tone(f, spb * 4) * 0.5, t, 0.06)
            continue
        add(buf, kick(), t, 0.9 * loud)
        truth["kicks"].append(round(t, 4))
        if pos in (1, 3):
            add(buf, snare(seed=i), t, 0.55 * loud)
            truth["snares"].append(round(t, 4))
        add(buf, tone(roots[bar % 4], spb * 0.9, saw=True), t, 0.22 * loud)
        if t >= DROP:  # lead stabs on the off-beat
            add(buf, tone(roots[bar % 4] * 8, spb * 0.4, saw=True), t + spb / 2, 0.12)
    buf[int(STOP[0] * SR):int(STOP[1] * SR)] = 0.0
    # the audible stop starts where the last note before the cut ends (it can be before STOP[0])
    live = np.where(np.abs(buf[:int(STOP[1] * SR)]) > 1e-4)[0]
    truth["silences"] = [{"start": round((live[-1] + 1) / SR, 4), "end": round(STOP[1], 4)}]
    buf *= 0.9 / np.abs(buf).max()
    st = np.stack([buf, buf], 1).astype(np.float32)
    truth["duration"] = DUR
    truth["sample_rate"] = SR
    return st, truth


async def _tts(text, voice, path):
    import edge_tts
    await edge_tts.Communicate(text, voice).save(str(path))


def make_vocalmix(instr):
    mp3 = OUT / "_vo_line.mp3"
    asyncio.run(_tts(VO_TEXT, VO_VOICE, mp3))
    vo = al.decode(mp3, SR, 2)
    voc = np.zeros_like(instr)
    al.place(voc, vo, VO_AT, sr=SR)
    voc *= 0.5 / max(np.abs(voc).max(), 1e-9)
    inst = instr * 0.6
    mix = voc + inst
    peak = np.abs(mix).max()
    if peak > 0.95:
        voc, inst, mix = voc * 0.95 / peak, inst * 0.95 / peak, mix * 0.95 / peak
    live = np.where(np.abs(voc[:, 0]) > 1e-3)[0]
    truth = {"vocal_span": [round(live[0] / SR, 3), round(live[-1] / SR, 3)], "text": VO_TEXT,
             "voice": VO_VOICE, "language": "mr", "duration": DUR, "sample_rate": SR}
    mp3.unlink()
    return mix, voc, inst, truth


SPEECH = {
    "mr": ("गोव्यातील प्राणी मुक्ती मोर्चा या रविवारी पणजीत होणार आहे. "
           "आपल्या शहरातील रस्त्यांवर राहणाऱ्या कुत्र्यांना आणि गायींना प्रेमाने वागवा.",
           {"f": "mr-IN-AarohiNeural", "m": "mr-IN-ManoharNeural"}),
    "hi": ("गोवा में पशु मुक्ति मार्च इस रविवार पणजी में होगा. "
           "हमारे शहर की सड़कों पर रहने वाले कुत्तों और गायों के साथ प्यार से पेश आइए.",
           {"f": "hi-IN-SwaraNeural", "m": "hi-IN-MadhurNeural"}),
    "en": ("The Goa Animal Liberation March will take place this Sunday in Panaji. "
           "Please treat the dogs and cows living on our city streets with kindness.",
           {"f": "en-IN-NeerjaExpressiveNeural", "m": "en-IN-PrabhatNeural"}),
}
SPEECH_SR = 16000


async def _tts_words(text, voice, path):
    import edge_tts
    c = edge_tts.Communicate(text, voice, boundary="WordBoundary")
    words, audio = [], bytearray()
    async for ch in c.stream():
        if ch["type"] == "audio":
            audio += ch["data"]
        elif ch["type"] == "WordBoundary":
            t0 = ch["offset"] / 1e7
            words.append({"text": ch["text"], "start": round(t0, 3), "end": round(t0 + ch["duration"] / 1e7, 3)})
    Path(path).write_bytes(bytes(audio))
    return words


def make_speech():
    for lang, (text, voices) in SPEECH.items():
        for g, voice in voices.items():
            mp3 = OUT / f"_speech_{lang}_{g}.mp3"
            words = asyncio.run(_tts_words(text, voice, mp3))
            y = al.decode(mp3, SPEECH_SR, 1)
            mp3.unlink()
            name = f"speech_{lang}_{g}"
            al.write_wav(OUT / f"{name}.wav", y, SPEECH_SR)
            truth = {"language": lang, "voice": voice, "text": text, "words": words,
                     "duration": round(len(y) / SPEECH_SR, 3), "timing_source": "edge-tts WordBoundary"}
            (OUT / f"{name}.truth.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"{name}.wav: {len(words)} words, {truth['duration']} s")


def _trim(y: np.ndarray, sr: int, db_floor: float = -40.0) -> np.ndarray:
    """Cut leading/trailing audio quieter than db_floor relative to the clip peak (5 ms frames)."""
    hop = int(0.005 * sr)
    n = len(y) // hop
    e = 20 * np.log10(np.sqrt((y[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    live = np.where(e > e.max() + db_floor)[0]
    return y[live[0] * hop:(live[-1] + 1) * hop] if len(live) else y[:0]


def make_words():
    import re
    rng = np.random.default_rng(7)
    for lang, (text, voices) in SPEECH.items():
        voice = voices["f"]
        words = text.split()
        parts, truth_words = [np.zeros(int(0.3 * SPEECH_SR))], []
        t = 0.3
        for w in words:
            clean = re.sub(r"[.,!?।]", "", w)
            mp3 = OUT / "_word.mp3"
            asyncio.run(_tts(clean, voice, mp3))
            y = _trim(al.decode(mp3, SPEECH_SR, 1)[:, 0], SPEECH_SR)
            mp3.unlink()
            truth_words.append({"text": w, "start": round(t, 4), "end": round(t + len(y) / SPEECH_SR, 4)})
            gap = float(rng.uniform(0.08, 0.25))
            parts += [y, np.zeros(int(gap * SPEECH_SR))]
            t += len(y) / SPEECH_SR + int(gap * SPEECH_SR) / SPEECH_SR
        y = np.concatenate(parts + [np.zeros(int(0.3 * SPEECH_SR))]).astype(np.float32)
        y *= 0.9 / np.abs(y).max()
        name = f"words_{lang}"
        al.write_wav(OUT / f"{name}.wav", y, SPEECH_SR)
        truth = {"language": lang, "voice": voice, "text": text, "words": truth_words,
                 "duration": round(len(y) / SPEECH_SR, 3), "timing_source": "exact (concatenated words)"}
        (OUT / f"{name}.truth.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{name}.wav: {len(truth_words)} words, {truth['duration']} s (exact timings)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["beat", "vocalmix", "speech", "words"])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    instr, truth = make_beat()
    if a.only in (None, "beat"):
        al.write_wav(OUT / "beat_128.wav", instr, SR)
        (OUT / "beat_128.truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
        print(f"beat_128.wav: {len(truth['beats'])} beats, drop at {DROP}s")
    if a.only in (None, "vocalmix"):
        mix, voc, inst, t2 = make_vocalmix(instr)
        al.write_wav(OUT / "vocalmix.wav", mix, SR)
        al.write_wav(OUT / "vocalmix_vocals.wav", voc, SR)
        al.write_wav(OUT / "vocalmix_instrumental.wav", inst, SR)
        (OUT / "vocalmix.truth.json").write_text(json.dumps(t2, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"vocalmix.wav: vocals {t2['vocal_span']}")
    if a.only in (None, "speech"):
        make_speech()
    if a.only in (None, "words"):
        make_words()
    return 0


if __name__ == "__main__":
    sys.exit(main())

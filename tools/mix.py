"""Soundtrack mix for a build (ported from the Goa reel's audio.py): music + VO + clip sound + SFX.

Used by tools/build.py: mix(spec, out_wav) -> loudness dict. Steps:
- music: the used range [from, from + (until - at)], optional upward compression (`compress`,
  for quiet beds under VO), set to a bed level, faded, placed at `at`; `rides` lower or raise it
  over spans ({from, to, db}, 0.25 s ramps) e.g. a silence before a drop
- VO lines: normalised to -20 dBFS RMS (the anchor everything is relative to)
- clip sound: placed at each clip's timeline start with its gain
- SFX: from library/sfx (align "onset" puts the start on `at`; "end" puts the END on `at`)
- ducking: music dips by `duck_db` (default -9 dB) while words are spoken (VO words + caption
  words), envelope follower with 100 ms lookahead, ~120 ms attack, ~300 ms release
- master: 1.2 s fade at the end, headroom, then two-pass loudnorm to -14 LUFS / -1.5 dBTP
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import audiolib as al  # noqa: E402

SR = al.SR
VO_RMS = 0.10           # -20 dBFS
BED_RMS = 0.10          # music alone (no VO): same level as speech would be
BED_UNDER_VO = 0.045    # music under VO (~ -27 dBFS): Goa reel levels


def _rms_active(x: np.ndarray, floor_db: float = -45) -> float:
    """RMS over the non-silent part (VO clips carry pauses)."""
    m = x if x.ndim == 1 else x.mean(1)
    win = int(0.05 * SR)
    if len(m) < win:
        return al.rms(x)
    frames = m[: len(m) // win * win].reshape(-1, win)
    r = np.sqrt((frames ** 2).mean(1) + 1e-12)
    act = r[20 * np.log10(r + 1e-12) > floor_db]
    return float(np.sqrt((act ** 2).mean())) if len(act) else al.rms(x)


def duck_env(mask: np.ndarray, lookahead: float = 0.10, attack: float = 0.12, release: float = 0.30) -> np.ndarray:
    """0..1 envelope from a 0/1 speech mask, computed at 1 kHz, shifted earlier by the lookahead."""
    step = SR // 1000
    small = mask[::step].astype(np.float32)
    la = int(lookahead * 1000)
    if la:
        small = np.concatenate([small[la:], np.zeros(la, np.float32)])
        small = np.maximum(small, mask[::step][: len(small)])
    a_s, r_s = 1 - np.exp(-1 / (attack * 1000)), 1 - np.exp(-1 / (release * 1000))
    out = np.zeros_like(small)
    lvl = 0.0
    for i, v in enumerate(small):
        lvl += (v - lvl) * (a_s if v > lvl else r_s)
        out[i] = lvl
    env = np.repeat(out, step)[: len(mask)]
    return np.pad(env, (0, len(mask) - len(env)), mode="edge")


def mix(spec: dict, out_wav: Path, raw_wav: Path | None = None) -> dict:
    dur = float(spec["duration"])
    n = int(round(dur * SR))
    pad = n + 10 * SR
    music = np.zeros((pad, 2), np.float32)
    vo = np.zeros((pad, 2), np.float32)
    clip = np.zeros((pad, 2), np.float32)
    sfx = np.zeros((pad, 2), np.float32)
    speech = np.zeros(pad, np.float32)
    has_vo = bool(spec.get("vo"))

    m = spec.get("music")
    if m:
        y = al.decode(m["path"], SR, 2)
        length = float(m.get("until", dur)) - float(m.get("at", 0))
        seg = y[int(float(m.get("from", 0)) * SR): int((float(m.get("from", 0)) + length) * SR)]
        if m.get("compress"):
            seg = al.compress(seg, amount=float(m.get("compress_amount", 0.45)))
        target = BED_UNDER_VO if has_vo else BED_RMS
        seg = seg * (target / max(al.rms(seg), 1e-6)) * al.db(float(m.get("gain_db", 0)))
        seg = al.fade(seg, float(m.get("fade_in", 0.02)), float(m.get("fade_out", 0.05)))
        al.place(music, seg, float(m.get("at", 0)))
        t = np.arange(pad) / SR
        for r in m.get("rides", []):
            t0, t1, g = float(r["from"]), float(r["to"]), float(r["db"])
            ramp = np.clip((t - t0) / 0.25 + 1, 0, 1) * np.clip((t1 - t) / 0.25 + 1, 0, 1)
            music *= al.db(g * ramp)[:, None]

    for line in spec.get("vo", []):
        y = al.decode(line["path"], SR, 2)
        y = y * (VO_RMS / max(_rms_active(y), 1e-6)) * al.db(float(line.get("gain_db", 0)))
        al.place(vo, y, float(line["at"]))

    for c in spec.get("clips", []):
        y = al.decode(c["path"], SR, 2) * al.db(float(c.get("gain_db", 0)))
        if c.get("normalize", True):
            y = y * (VO_RMS / max(_rms_active(y), 1e-6))
        al.place(clip, y, float(c["at"]))

    for s in spec.get("sfx", []):
        y = al.decode(s["path"], SR, 2)
        at = float(s["at"]) - (len(y) / SR if s.get("align") == "end" else 0) - float(s.get("pre", 0))
        al.place(sfx, y * al.db(float(s.get("gain_db", 0))) * 0.5, max(0.0, at))

    for w in spec.get("speech_words", []):
        speech[int(max(0, w["start"] - 0.02) * SR): int((w["end"] + 0.06) * SR)] = 1
    if m and speech.any():
        music *= al.db(float(m.get("duck_db", -9)) * duck_env(speech))[:, None]

    mixbuf = (music + vo + clip + sfx)[:n]
    tail = min(int(float(spec.get("fade_out", 1.2)) * SR), n)
    if tail:
        mixbuf[n - tail:] *= (np.cos(np.linspace(0, np.pi / 2, tail)) ** 2)[:, None]
    peak = np.abs(mixbuf).max()
    if peak > 0:
        mixbuf *= 0.89 / peak
    raw = raw_wav or out_wav.with_name(out_wav.stem + "_raw.wav")
    al.write_wav(raw, mixbuf, SR)
    if peak <= 0:  # silent video: keep silence, no loudnorm
        al.write_wav(out_wav, mixbuf, SR)
        return {"I": None, "TP": None, "silent": True}
    # AAC (every export) overshoots on sharp transients and sub-bass: a boom + impact mix mastered to
    # -2.5 dBTP came out at +0.3 dBTP after AAC. A 30 Hz high-pass (also removes DC) and a 5 ms
    # look-ahead limiter before the two-pass loudnorm keep the AAC file at about -3 dBTP, -14 LUFS.
    pre = raw.with_name(raw.stem + "_pre.wav")
    subprocess.run([cfg.ffmpeg(), "-v", "error", "-y", "-i", str(raw), "-af",
                    "highpass=f=30,alimiter=limit=0.5:attack=5:release=60:level=false", str(pre)], check=True)
    al.master(pre, out_wav, target=spec.get("loudness", "I=-14:TP=-2.5:LRA=11"))
    pre.unlink()
    return al.loudness(out_wav)

"""Shared audio helpers. Ported from the Goa reel's render/audio.py.

decode/write via the pinned FFmpeg, level helpers, the level-riding compressor,
synthesized SFX (boom/thud/riser/whoosh) and two-pass EBU R128 mastering.
All buffers are float32 arrays shaped (n, channels).
"""
from __future__ import annotations

import json
import re
import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve

import studio_config as cfg

SR = 48000


# ------------------------------------------------------------------ io ---

def decode(path: str | Path, sr: int = SR, channels: int = 2) -> np.ndarray:
    raw = subprocess.run([cfg.ffmpeg(), "-v", "error", "-i", str(path), "-ac", str(channels),
                          "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, channels).copy()


def decode_mono(path: str | Path, sr: int = 22050) -> np.ndarray:
    return decode(path, sr, 1)[:, 0]


def write_wav(path: str | Path, x: np.ndarray, sr: int = SR) -> Path:
    """16-bit PCM WAV. Clips to [-1, 1]."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    x = np.atleast_2d(x.T).T if x.ndim == 1 else x
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


# -------------------------------------------------------------- levels ---

def db(x: float | np.ndarray) -> float | np.ndarray:
    return 10 ** (np.asarray(x) / 20)


def rms(x: np.ndarray) -> float:
    """RMS over the non-silent part of a clip."""
    x2 = x if x.ndim == 2 else x[:, None]
    live = x2[np.abs(x2).sum(1) > 1e-4]
    return float(np.sqrt(np.mean(live ** 2) + 1e-12)) if len(live) else 0.0


def compress(x: np.ndarray, amount: float = 0.45, window: float = 0.35, sr: int = SR) -> np.ndarray:
    """Smooth level-riding (upward) compressor: lifts the quiet passages of a bed.

    gain = (env_ref / env) ** amount, limited to +12 / -4 dB.
    """
    k = int(window * sr)
    c = np.concatenate([[0.0], np.cumsum((x.astype(np.float64) ** 2).mean(1))])
    idx = np.arange(len(x))
    lo, hi = np.clip(idx - k // 2, 0, len(x)), np.clip(idx + k // 2, 0, len(x))
    power = (c[hi] - c[lo]) / np.maximum(hi - lo, 1)  # moving average via cumsum
    env = np.sqrt(power + 1e-10)
    ref = np.percentile(env[env > 1e-4], 90)
    gain = np.clip((ref / env) ** amount, db(-4), db(12))
    return x * gain[:, None].astype(np.float32)


def place(buf: np.ndarray, clip: np.ndarray, t: float, gain: float = 1.0, sr: int = SR) -> None:
    i = int(round(t * sr))
    if i < 0:
        clip, i = clip[-i:], 0
    n = min(len(clip), len(buf) - i)
    if n > 0:
        buf[i:i + n] += clip[:n] * gain


def fade(clip: np.ndarray, fin: float, fout: float, sr: int = SR) -> np.ndarray:
    clip = clip.copy()
    n_in, n_out = int(fin * sr), int(fout * sr)
    if n_in:
        clip[:n_in] *= (np.sin(np.linspace(0, np.pi / 2, n_in)) ** 2)[:, None]
    if n_out:
        clip[-n_out:] *= (np.cos(np.linspace(0, np.pi / 2, n_out)) ** 2)[:, None]
    return clip


# ----------------------------------------------------------------- SFX ---

def _reverb(x: np.ndarray, seconds: float = 1.6, mix: float = 0.25, seed: int = 1, sr: int = SR) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    ir = rng.normal(0, 1, n) * np.exp(-np.linspace(0, 7, n))
    ir /= np.sqrt((ir ** 2).sum())
    wet = fftconvolve(x, ir)[: len(x) + n]
    out = np.zeros(len(wet))
    out[: len(x)] = x
    return out * (1 - mix) + wet * mix


def boom(length: float = 3.0, f0: float = 95, f1: float = 34, sr: int = SR) -> np.ndarray:
    """Cinematic sub impact: pitch-dropping sine + noise transient + tail."""
    n = int(length * sr)
    t = np.arange(n) / sr
    freq = f1 + (f0 - f1) * np.exp(-t * 9)
    body = np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-t * 1.6)
    rng = np.random.default_rng(3)
    click = rng.normal(0, 1, n) * np.exp(-t * 60) * 0.35
    rumble = np.convolve(rng.normal(0, 1, n), np.ones(120) / 120, mode="same") * np.exp(-t * 2.2) * 1.8
    x = _reverb(body + click + rumble, 2.2, 0.3, sr=sr)
    x = np.tanh(x * 1.4)
    x /= np.abs(x).max()
    return np.stack([x, x], 1).astype(np.float32)


def thud(length: float = 1.4, sr: int = SR) -> np.ndarray:
    return boom(length, f0=120, f1=48, sr=sr) * 0.8


def riser(length: float = 2.0, sr: int = SR) -> np.ndarray:
    """Filtered-noise swell rising into a hit, ends abruptly."""
    n = int(length * sr)
    t = np.arange(n) / sr
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 1, (n, 2))
    cut = 300 + 6000 * (t / length) ** 2.2  # one-pole low-pass sweeping upward
    a = np.exp(-2 * np.pi * cut / sr)
    y = np.zeros_like(noise)
    acc = np.zeros(2)
    for i in range(n):
        acc = (1 - a[i]) * noise[i] + a[i] * acc
        y[i] = acc
    env = (t / length) ** 2.5
    tone = np.sin(2 * np.pi * np.cumsum(180 + 420 * (t / length) ** 2) / sr)[:, None] * 0.25
    x = (y / np.abs(y).max() + tone) * env[:, None]
    return (x / np.abs(x).max()).astype(np.float32)


def whoosh(length: float = 0.9, sr: int = SR) -> np.ndarray:
    n = int(length * sr)
    t = np.arange(n) / sr
    rng = np.random.default_rng(11)
    noise = rng.normal(0, 1, (n, 2))
    k = 40
    smooth = np.stack([np.convolve(noise[:, c], np.ones(k) / k, mode="same") for c in range(2)], 1)
    env = np.sin(np.pi * np.clip(t / length, 0, 1)) ** 3
    x = smooth * env[:, None]
    return (x / np.abs(x).max()).astype(np.float32)


SFX_BANK = {"boom": boom, "thud": thud, "riser": riser, "whoosh": whoosh}


# ------------------------------------------------------------ loudness ---

def loudness(path: str | Path) -> dict:
    """Integrated loudness (LUFS), loudness range (LU) and true peak (dBTP) via ebur128."""
    err = subprocess.run([cfg.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-af",
                          "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stderr
    summary = err[err.rfind("Summary:"):]

    def grab(label: str) -> float | None:
        m = re.search(rf"{label}:\s+(-?[\d.]+|-inf)", summary)
        if not m:
            return None
        return float("-inf") if m.group(1) == "-inf" else float(m.group(1))

    return {"I": grab("I"), "LRA": grab("LRA"), "TP": grab("Peak")}


def master(src: str | Path, dst: str | Path, target: str = "I=-14:TP=-1.5:LRA=11", sr: int = SR) -> dict:
    """Two-pass EBU R128 loudness normalisation (Instagram/YouTube ~ -14 LUFS)."""
    probe = subprocess.run([cfg.ffmpeg(), "-hide_banner", "-i", str(src), "-af",
                            f"loudnorm={target}:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    af = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
          f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
          f":offset={m['target_offset']}:linear=true")
    subprocess.run([cfg.ffmpeg(), "-y", "-v", "error", "-i", str(src), "-af", af, "-ar", str(sr), str(dst)],
                   check=True)
    return m

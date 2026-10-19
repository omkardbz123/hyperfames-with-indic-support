"""Silence cutting (auto-editor) and voice denoise (DeepFilterNet3) with known truth.

Usage:  uv run tests/eval_audio_fx.py

Silence cut: a 'talking head' mp4 (still frame + speech_en_f, speech_hi_f, speech_mr_f with known
pauses of 0.8 / 2.0 / 1.5 / 1.0 s) -> tools/fx.py cut-silence. Pass: >= 70 % of the pause time
removed and >= 97 % of the voiced time kept.
Denoise: speech_en_f + white noise + 50 Hz hum at 5 dB SNR -> tools/fx.py denoise-voice.
Pass: SI-SDR vs the clean speech (same 80 Hz high-pass) improves by >= 8 dB and the noise floor
between words drops by >= 20 dB.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import audiolib as al  # noqa: E402
import fx  # noqa: E402

FX = ROOT / "tests" / "fixtures"
OUT = FX / "fx"
SR = 48000


def voiced_seconds(y: np.ndarray, sr: int) -> float:
    hop = sr // 100
    n = len(y) // hop
    e = 20 * np.log10(np.sqrt((y[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    return float((e > e.max() - 35).sum() * 0.01)


def si_sdr(est: np.ndarray, ref: np.ndarray) -> float:
    n = min(len(est), len(ref))
    est, ref = est[:n] - est[:n].mean(), ref[:n] - ref[:n].mean()
    a = (est @ ref) / (ref @ ref + 1e-12)
    t = a * ref
    return float(10 * np.log10((t @ t) / ((est - t) @ (est - t) + 1e-12)))


def align(est: np.ndarray, ref: np.ndarray) -> np.ndarray:
    from scipy.signal import correlate
    c = correlate(est[: SR * 6], ref[: SR * 6], mode="full", method="fft")
    lag = int(np.argmax(c)) - (SR * 6 - 1)
    return est[lag:] if lag > 0 else np.r_[np.zeros(-lag), est]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ok = True
    # ---- silence cut
    pauses = [0.8, 2.0, 1.5, 1.0]
    parts = [np.zeros(int(pauses[0] * SR))]
    for clip, gap in zip(["speech_en_f", "speech_hi_f", "speech_mr_f"], pauses[1:]):
        parts += [al.decode_mono(FX / f"{clip}.wav", SR), np.zeros(int(gap * SR))]
    y = np.concatenate(parts).astype(np.float32)
    wav = OUT / "talk.wav"
    al.write_wav(wav, y, SR)
    still = OUT / "talk.mp4"
    fx.ff("-loop", "1", "-framerate", "30", "-i", str(OUT / "orig_1080.png"), "-i", str(wav), "-shortest",
          "-vf", "scale=1280:-2", *fx.ENC, "-c:a", "aac", "-b:a", "192k", str(still))
    r = fx.cut_silence(still, OUT / "talk_cut.mp4", threshold="4%", margin="0.2s")
    y2 = al.decode_mono(OUT / "talk_cut.mp4", SR)
    pause_in = sum(pauses) + sum(  # the clips' own lead/tail silence counts as pause too
        len(al.decode_mono(FX / f"{c}.wav", SR)) / SR for c in ["speech_en_f", "speech_hi_f", "speech_mr_f"]
    ) - voiced_seconds(y, SR)
    removed = r["in_s"] - r["out_s"]
    kept = voiced_seconds(y2, SR) / voiced_seconds(y, SR)
    c_ok = removed >= 0.7 * sum(pauses) and kept >= 0.97
    ok &= c_ok
    print(f"{'PASS' if c_ok else 'FAIL'}  cut-silence: {r['in_s']} s -> {r['out_s']} s (removed {removed:.2f} s of "
          f"{sum(pauses):.1f} s inserted pauses, ~{pause_in:.1f} s quiet in total); voiced time kept {kept:.1%} "
          f"({r['seconds']} s)")
    # ---- voice denoise
    clean = al.decode_mono(FX / "speech_en_f.wav", SR)
    rng = np.random.default_rng(3)
    t = np.arange(len(clean)) / SR
    noise = rng.normal(0, 1, len(clean)) + 0.8 * np.sin(2 * np.pi * 50 * t) + 0.3 * np.sin(2 * np.pi * 150 * t)
    noise *= np.sqrt((clean ** 2).mean() / (noise ** 2).mean()) / 10 ** (5 / 20)  # 5 dB SNR
    noisy = (clean + noise).astype(np.float32)
    noisy *= 0.9 / np.abs(noisy).max()
    al.write_wav(OUT / "noisy.wav", noisy, SR)
    r = fx.denoise_voice(OUT / "noisy.wav", OUT / "denoised.wav")
    den = align(al.decode_mono(OUT / "denoised.wav", SR), clean)
    # the chain high-passes at 80 Hz, so compare against the clean voice through the same filter
    fx.ff("-i", str(FX / "speech_en_f.wav"), "-ar", str(SR), "-af",
          "highpass=f=80:poles=2,highpass=f=80:poles=2", str(OUT / "clean_hp.wav"))
    ref = al.decode_mono(OUT / "clean_hp.wav", SR)
    s0, s1 = si_sdr(noisy, ref), si_sdr(den, ref)
    hop = SR // 100
    n = len(clean) // hop
    e = 20 * np.log10(np.sqrt((clean[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    gaps = np.repeat(e < e.max() - 45, hop)

    def floor(y):
        y = y[: len(gaps)]
        return 10 * np.log10((y[gaps[: len(y)]] ** 2).mean() + 1e-12)

    f0, f1 = floor(noisy), floor(den)
    d_ok = s1 - s0 >= 8 and f0 - f1 >= 20
    ok &= d_ok
    print(f"{'PASS' if d_ok else 'FAIL'}  denoise-voice: SI-SDR {s0:.1f} -> {s1:.1f} dB (+{s1 - s0:.1f}); noise floor "
          f"between words {f0:.1f} -> {f1:.1f} dB ({f1 - f0:+.1f}); {r['seconds']} s for {len(clean) / SR:.1f} s")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

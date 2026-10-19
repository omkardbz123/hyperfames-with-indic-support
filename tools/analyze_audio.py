"""Analyse a music/audio file once and cache the facts the edit needs.

Usage:  uv run tools/analyze_audio.py <file> [--stems] [--no-tags] [--no-hf] [--fresh] [--quiet]

Writes analysis/<asset-id>/audio.json (schema: docs/CONTRACTS.md) and audio.png, an
annotated energy / spectrogram chart with beats, downbeats, sections, drops and hits.

- beats / downbeats: Beat This! (CPJKU, final0, CPU); librosa fallback
- bpm + beat_grid_reliable: false for sparse / rubato music -> recipes pace by phrase/energy
- energy: RMS every 50 ms (relative 0..1) ; onsets: all + band-split kick / snare / hi-hat
  (drums stem when --stems), refined to ~1 ms on a 10 ms energy-flux envelope
- hits (strong accents), silences, sections (silence edges, kick stops/returns, energy steps,
  one-bar dips/fills, timbre novelty; snapped to downbeats), drops (level jump or kick return, timed to the first kick)
- loudness: ffmpeg ebur128 (I, LRA, true peak)
- tags: CLAP zero-shot mood/genre (laion/larger_clap_music_and_speech -> clap-htsat-unfused)
- hyperframes: `hyperframes audio --quality local` cross-check (kind, bpm, sections)
Precise timing comes only from here, never from Gemini.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()
cfg.model_cache_env()
warnings.filterwarnings("ignore")

import audiolib as al  # noqa: E402
import assets  # noqa: E402

SR = 22050
HOP = 256                    # STFT hop for onset envelopes (11.6 ms)
ENERGY_HOP = 0.05            # s
SCHEMA_VERSION = 1

CLAP_MODELS = ["laion/larger_clap_music_and_speech", "laion/clap-htsat-unfused"]
CLAP_LABELS = [
    "aggressive phonk", "drift phonk", "sad piano", "epic orchestral", "uplifting corporate",
    "Bollywood romantic", "Marathi folk lavani", "dhol festive Indian percussion",
    "devotional bhajan", "lo-fi hip-hop", "EDM drop", "hip-hop beat", "ambient",
    "cinematic tension", "horror", "comedy quirky", "rock", "acoustic folk", "jazz",
    "classical Indian raga", "trap", "house dance music", "synthwave retro",
    "inspirational emotional", "dark electronic", "children's playful", "spoken word speech",
]



# ------------------------------------------------------------------ utils ---

def r3(x) -> float:
    return round(float(x), 3)


def r3l(xs) -> list[float]:
    return [r3(x) for x in xs]


def log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg, flush=True)


# ------------------------------------------------------------------ beats ---

def beats_beat_this(y: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
    from beat_this.inference import Audio2Beats
    a2b = Audio2Beats(checkpoint_path="final0", device="cpu", dbn=False)
    b, d = a2b(y.astype(np.float32), SR)
    return np.asarray(b, float), np.asarray(d, float), "beat_this:final0"


def beats_librosa(y: np.ndarray) -> tuple[np.ndarray, np.ndarray, str]:
    import librosa
    _, frames = librosa.beat.beat_track(y=y, sr=SR, hop_length=512)
    b = librosa.frames_to_time(frames, sr=SR, hop_length=512)
    return b, b[::4], "librosa.beat_track"


def fit_bpm(beats: np.ndarray) -> float | None:
    """Tempo from a least-squares line through steady runs of beats.

    Beat This! reports beats on a 20 ms frame grid, so a median interval is biased
    (128 BPM read as 130.4). A per-run linear fit averages that quantisation out.
    """
    if len(beats) < 4:
        return None
    ibi = np.diff(beats)
    med = np.median(ibi)
    runs, cur = [], [0]
    for i, d in enumerate(ibi):
        if 0.75 * med < d < 1.25 * med:
            cur.append(i + 1)
        else:
            if len(cur) >= 4:
                runs.append(cur)
            cur = [i + 1]
    if len(cur) >= 4:
        runs.append(cur)
    if not runs:
        return round(60.0 / float(med), 2)
    num = den = 0.0
    for r in runs:
        idx = np.arange(len(r))
        slope = np.polyfit(idx, beats[r], 1)[0]
        num += slope * (len(r) - 1)
        den += len(r) - 1
    return round(60.0 / (num / den), 2)


def snap_beats(beats: np.ndarray, onsets: np.ndarray, tol: float = 0.035) -> np.ndarray:
    """Move each beat onto the precise onset within ±tol, if there is one."""
    if not len(onsets):
        return beats
    out = beats.copy()
    for i, b in enumerate(beats):
        j = np.argmin(np.abs(onsets - b))
        if abs(onsets[j] - b) <= tol:
            out[i] = onsets[j]
    return out


def beat_grid_quality(beats: np.ndarray, onsets: np.ndarray, duration: float) -> dict:
    if len(beats) < 8:
        return {"reliable": False, "ibi_cv": None, "onset_agreement": 0.0, "coverage": 0.0,
                "reason": "fewer than 8 beats"}
    ibi = np.diff(beats)
    med = np.median(ibi)
    steady = ibi[(ibi > 0.5 * med) & (ibi < 1.5 * med)]  # ignore gaps from breaks
    cv = float(np.std(steady) / np.mean(steady)) if len(steady) > 2 else 1.0
    if len(onsets):
        near = np.min(np.abs(beats[:, None] - onsets[None, :]), axis=1)
        agree = float(np.mean(near < 0.07))
    else:
        agree = 0.0
    coverage = float(np.sum(np.clip(ibi, 0, 1.5 * med)) / max(duration, 1e-6))
    reliable = cv < 0.08 and agree >= 0.6 and coverage >= 0.4
    reasons = []
    if cv >= 0.08:
        reasons.append(f"tempo wanders (IBI CV {cv:.2f})")
    if agree < 0.6:
        reasons.append(f"beats rarely land on onsets ({agree:.0%})")
    if coverage < 0.4:
        reasons.append(f"beats cover {coverage:.0%} of the track")
    return {"reliable": reliable, "ibi_cv": round(cv, 4), "onset_agreement": round(agree, 3),
            "coverage": round(coverage, 3), "reason": "; ".join(reasons) or "steady grid on onsets"}


# ----------------------------------------------------------------- onsets ---

def fine_envelope(y: np.ndarray, win: float = 0.010, hop: float = 0.001) -> tuple[np.ndarray, float]:
    """RMS energy at 1 ms hop over 10 ms windows (for precise accent times)."""
    w, h = int(win * SR), max(1, int(hop * SR))
    c = np.concatenate([[0.0], np.cumsum(y.astype(np.float64) ** 2)])
    starts = np.arange(0, len(y) - w, h)
    return np.sqrt((c[starts + w] - c[starts]) / w), h / SR


def refine(times: np.ndarray, flux: np.ndarray, fhop: float, radius: float = 0.04) -> np.ndarray:
    """Move each onset to the energy-flux peak within ±radius (10 ms window, 1 ms hop).

    The flux sample i compares window i+1 vs i; the attack instant is ~ the window start
    plus half a window, so report t = (i + 1) * hop + 5 ms.
    """
    out = []
    r = int(radius / fhop)
    for t in times:
        c = int(t / fhop)
        lo, hi = max(0, c - r), min(len(flux), c + r)
        if hi <= lo:
            out.append(t)
            continue
        i = lo + int(np.argmax(flux[lo:hi]))
        out.append((i + 1) * fhop + 0.005)
    return np.asarray(out)


def pick_peaks(env: np.ndarray, hop_s: float, min_gap: float, rel: float) -> np.ndarray:
    """Local maxima above rel * 99th percentile, at least min_gap apart (strongest wins)."""
    if not len(env) or env.max() <= 0:
        return np.array([])
    thr = rel * np.percentile(env, 99)
    gap = max(1, int(min_gap / hop_s))
    cand = np.where((env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > thr))[0] + 1
    keep: list[int] = []
    for i in cand[np.argsort(-env[cand])]:
        if all(abs(i - k) >= gap for k in keep):
            keep.append(i)
    return np.sort(np.asarray(keep)) * hop_s


def onsets_all(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import librosa
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    fr = librosa.onset.onset_detect(onset_envelope=env, sr=SR, hop_length=HOP, backtrack=False)
    t = librosa.frames_to_time(fr, sr=SR, hop_length=HOP)
    strength = env[fr] / (env.max() + 1e-9)
    return t, strength


DRUM_BANDS = {"sub": (30, 120), "body": (170, 350), "mid": (1500, 5000), "high": (7000, 11000)}


def band_onsets(y: np.ndarray, flux: np.ndarray, fhop: float) -> dict[str, list[float]]:
    """Kick / snare / hi-hat times: candidate onsets classified by per-band level jumps.

    Candidates come from spectral flux in each band (union, merged within 30 ms). For each
    candidate the level change (dB, 35 ms after vs 35 ms before) is measured in sub / body /
    mid / high bands, relative to that band's typical level:
      kick  : sub jumps >= 6 dB and is loud
      snare : body >= 3 dB and mid >= 6 dB, body decays >= 6 dB within 80 ms (a drum, not
              a sustained chord), and mid/body are near the track's loudest (> -4 / -8 dB)
      hi-hat: high >= 6 dB and loud
    Each band's jump is measured at that band's own onset within ±25 ms, so a hi-hat on
    the same beat as a kick is still seen. Kick, snare and hi-hat can share a time.
    """
    import librosa
    S = np.abs(librosa.stft(y, n_fft=1024, hop_length=HOP)) ** 2
    freqs = librosa.fft_frequencies(sr=SR, n_fft=1024)
    hop_s = HOP / SR
    lv = {k: 10 * np.log10(S[(freqs >= lo) & (freqs < hi)].sum(0) + 1e-10) for k, (lo, hi) in DRUM_BANDS.items()}
    cands = []
    for k in DRUM_BANDS:
        env = np.concatenate([[0], np.maximum(0, np.diff(lv[k]))])
        cands += list(pick_peaks(env, hop_s, 0.05, rel=0.25))
    cands = np.sort(np.asarray(cands))
    merged: list[float] = []
    for c in cands:
        if not merged or c - merged[-1] > 0.03:
            merged.append(c)
    w = max(1, int(0.035 / hop_s))
    ref = {k: np.percentile(v, 95) for k, v in lv.items()}
    search = max(1, int(0.025 / hop_s))
    decay_n = max(1, int(0.08 / hop_s))
    out: dict[str, list[tuple[float, float]]] = {"kick": [], "snare": [], "hihat": []}
    for c in merged:
        c_i = int(round(c / hop_s))
        jump, level, decay = {}, {}, {}
        for k, v in lv.items():
            best = (-1e9, 0.0, 0.0)
            for i in range(max(w + 1, c_i - search), min(len(v) - w, c_i + search + 1)):
                pre = v[i - w - 1:i - 1].mean()
                post = v[i:i + w].max()
                if post - pre > best[0]:
                    pk = i + int(np.argmax(v[i:i + w]))
                    best = (post - pre, post - ref[k], post - v[min(len(v) - 1, pk + decay_n)])
            jump[k], level[k], decay[k] = best
        # level gates are dB relative to the band's 95th percentile over the whole track: a
        # snare is among the loudest mid-band events (kick-only beats sit ~-7, quiet hats ~-13)
        is_snare = (jump["body"] >= 3 and jump["mid"] >= 6 and decay["body"] >= 6
                    and level["mid"] > -4 and level["body"] > -8)
        if jump["sub"] >= 6 and level["sub"] > -12:
            out["kick"].append((c, jump["sub"] + level["sub"]))
        if is_snare:
            out["snare"].append((c, jump["mid"] + level["mid"]))
        if jump["high"] >= 6 and level["high"] > -20:
            out["hihat"].append((c, jump["high"] + level["high"]))
    # one hit per drum within its minimum spacing (strongest wins): a decaying kick or a
    # separated stem's tail can re-trigger the detector 50-130 ms later
    min_gap = {"kick": 0.09, "snare": 0.09, "hihat": 0.05}
    res: dict[str, list[float]] = {}
    for k, hits_ in out.items():
        keep: list[tuple[float, float]] = []
        for c, strength in sorted(hits_, key=lambda h: -h[1]):
            if all(abs(c - q) >= min_gap[k] for q, _ in keep):
                keep.append((c, strength))
        t = refine(np.sort(np.asarray([c for c, _ in keep])), flux, fhop, 0.03) if keep else np.array([])
        res[k] = r3l(np.unique(np.round(t, 3)))
    return res


# ----------------------------------------------------------- energy etc. ---

def energy_curve(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hop = int(ENERGY_HOP * SR)
    n = len(y) // hop
    frames = y[: n * hop].reshape(n, hop).astype(np.float64)
    rms = np.sqrt((frames ** 2).mean(1))
    dbfs = 20 * np.log10(rms + 1e-9)
    return rms, dbfs


def silences(dbfs: np.ndarray, fine: np.ndarray, fhop: float, min_len: float = 0.25) -> list[dict]:
    # quiet = below -45 dBFS AND 25 dB under the local median (±4 s), so the gaps in a
    # sparse, quiet intro are not mistaken for a stop
    from scipy.ndimage import median_filter
    local = median_filter(dbfs, size=int(8 / ENERGY_HOP) | 1, mode="nearest")
    quiet = (dbfs < -45) & ((dbfs < local - 25) | (dbfs < -70))
    out, i = [], 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            s, e = i * ENERGY_HOP, j * ENERGY_HOP
            if e - s >= min_len:
                # refine edges on the 1 ms envelope: the stop is the steepest level drop
                # near the coarse start, the re-entry the steepest rise near the coarse end
                fdb = 20 * np.log10(np.maximum(fine, 1e-7))
                d = np.diff(fdb)
                a, b = int(max(0, s - 0.12) / fhop), int(min(len(d), (s + 0.06) / fhop))
                s_ref = (a + int(np.argmin(d[a:b])) + 1) * fhop + 0.005 if b > a and s > 0 else s
                a, b = int(max(0, e - 0.06) / fhop), int(min(len(d), (e + 0.06) / fhop))
                e_ref = (a + int(np.argmax(d[a:b])) + 1) * fhop + 0.005 if b > a and j < len(quiet) else e
                out.append({"start": r3(s_ref), "end": r3(e_ref)})
            i = j
        else:
            i += 1
    return out


def hits(on_t: np.ndarray, on_s: np.ndarray, dbfs: np.ndarray, flux: np.ndarray, fhop: float) -> list[dict]:
    """Strong accents: top-decile onsets that also jump in level."""
    if not len(on_t):
        return []
    thr = np.percentile(on_s, 90)
    out = []
    for t, s in zip(on_t, on_s):
        if s < thr:
            continue
        k = int(t / ENERGY_HOP)
        before = dbfs[max(0, k - 6):k].mean() if k > 0 else -90
        after = dbfs[k:k + 3].mean() if k < len(dbfs) else -90
        jump = after - before
        if jump >= 1.5 or s >= np.percentile(on_s, 97):
            tt = refine(np.array([t]), flux, fhop, 0.04)[0]
            out.append({"t": r3(tt), "strength": round(float(s), 3), "jump_db": round(float(jump), 1)})
    return out


def kick_presence(beats: np.ndarray, kicks: list[float], tol: float = 0.06) -> np.ndarray:
    """1.0 for each beat that has a kick within ±tol, else 0.0."""
    if not len(beats):
        return np.array([])
    k = np.asarray(kicks)
    if not len(k):
        return np.zeros(len(beats))
    return (np.min(np.abs(beats[:, None] - k[None, :]), axis=1) <= tol).astype(float)


def density(times: list[float] | np.ndarray, beats: np.ndarray, t0: float, t1: float) -> float:
    """Events per beat in [t0, t1)."""
    nb = np.sum((beats >= t0) & (beats < t1))
    if nb == 0:
        return 0.0
    t = np.asarray(times)
    return float(np.sum((t >= t0) & (t < t1)) / nb)


def novelty_curve(y: np.ndarray) -> tuple[np.ndarray, float]:
    """Timbre/harmony novelty (checkerboard kernel on a 0.5 s self-similarity matrix)."""
    import librosa
    hop = 2048
    chroma = librosa.feature.chroma_cqt(y=y, sr=SR, hop_length=hop)
    mfcc = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=13, hop_length=hop)
    loud = librosa.feature.rms(y=y, hop_length=hop)
    feat = np.vstack([librosa.util.normalize(chroma, axis=0), mfcc / (np.abs(mfcc).max() + 1e-9),
                      3 * loud / (loud.max() + 1e-9)])
    feat = librosa.util.normalize(feat, axis=0)
    blk = max(1, int(round(0.5 * SR / hop)))
    nb = feat.shape[1] // blk
    if nb < 8:
        return np.zeros(max(nb, 1)), 0.5
    F = feat[:, : nb * blk].reshape(feat.shape[0], nb, blk).mean(2)
    F = F / (np.linalg.norm(F, axis=0, keepdims=True) + 1e-9)
    SSM = F.T @ F
    L = min(16, nb // 4)  # checkerboard half-width: 8 s
    g = np.outer(np.r_[np.ones(L), -np.ones(L)], np.r_[np.ones(L), -np.ones(L)])
    g *= np.outer(np.hanning(2 * L), np.hanning(2 * L))
    nov = np.zeros(nb)
    P = np.pad(SSM, L, mode="edge")
    for i in range(nb):
        nov[i] = (P[i:i + 2 * L, i:i + 2 * L] * g).sum()
    return np.maximum(nov, 0), blk * hop / SR


def energy_steps(dbfs: np.ndarray, win: float = 4.0, min_db: float = 4.0) -> list[float]:
    """Times where the mean level of the next `win` s differs from the previous by >= min_db."""
    lv = np.maximum(dbfs, -80)
    n = int(win / ENERGY_HOP)
    if len(lv) < 2 * n + 2:
        return []
    c = np.concatenate([[0.0], np.cumsum(lv)])
    idx = np.arange(n, len(lv) - n)
    step = (c[idx + n] - c[idx]) / n - (c[idx] - c[idx - n]) / n
    env = np.zeros(len(lv))
    env[idx] = np.abs(step)
    env[env < min_db] = 0
    return list(pick_peaks(env, ENERGY_HOP, min_gap=4.0, rel=0.0)) if env.any() else []


def kick_changes(beats: np.ndarray, presence: np.ndarray, span: int = 8, min_change: float = 0.6) -> list[float]:
    """Beats where kicks stop or come back (mean presence over the next vs previous `span` beats)."""
    out: list[tuple[float, float]] = []
    if presence.sum() < 8:
        return []
    for i in range(span, len(beats) - span + 1):
        change = abs(presence[i:i + span].mean() - presence[i - span:i].mean())
        if change < min_change:
            continue
        if out and beats[i] - out[-1][0] < 4.0:
            if change > out[-1][1]:
                out[-1] = (float(beats[i]), change)  # keep the strongest change in a cluster
        else:
            out.append((float(beats[i]), change))
    return [t for t, _ in out]


def bar_dips(downbeats: np.ndarray, dbfs: np.ndarray, min_db: float = 3.0, ctx: int = 4) -> list[float]:
    """Phrase boundaries from one-bar dips (fills, breaks): a bar >= min_db quieter than the
    median of the `ctx` bars on each side marks a boundary at the downbeat that ends it."""
    if len(downbeats) < 2 * ctx + 2:
        return []
    lv = np.maximum(dbfs, -80)
    bars = np.array([lv[int(a / ENERGY_HOP):max(int(a / ENERGY_HOP) + 1, int(b / ENERGY_HOP))].mean()
                     for a, b in zip(downbeats[:-1], downbeats[1:])])
    out = []
    for i in range(len(bars)):
        nb = np.r_[bars[max(0, i - ctx):i], bars[i + 1:i + 1 + ctx]]
        if len(nb) >= ctx and bars[i] <= np.median(nb) - min_db and bars[i] > -60:
            out.append(float(downbeats[i + 1]))
    return out


def find_sections(y: np.ndarray, duration: float, beats: np.ndarray, downbeats: np.ndarray,
                  sil: list[dict], dbfs: np.ndarray, kicks: list[float]) -> list[dict]:
    """Section boundaries from five cues, strongest first:
    silence edges > kick stops/returns > energy steps and one-bar dips > timbre novelty.
    Energy/novelty bounds snap to the nearest downbeat within 1 s."""
    nov, nov_hop = novelty_curve(y)
    presence = kick_presence(beats, kicks)
    cues: list[tuple[float, int]] = []
    for s in sil:
        if s["end"] - s["start"] >= 0.4:
            cues += [(s["start"], 3), (s["end"], 3)]
    cues += [(t, 2) for t in kick_changes(beats, presence)]
    cues += [(t, 1) for t in energy_steps(dbfs)]
    cues += [(t, 1) for t in bar_dips(downbeats, dbfs)]
    cues += [(t, 0) for t in pick_peaks(nov, nov_hop, min_gap=6.0, rel=0.35)]
    gaps = {3: 0.3, 2: 3.0, 1: 4.0, 0: 6.0}
    accepted: list[tuple[float, int]] = []
    for t, pr in sorted(cues, key=lambda c: -c[1]):
        if pr <= 1 and len(downbeats):
            d = downbeats[np.argmin(np.abs(downbeats - t))]
            if abs(d - t) <= 1.0:
                t = float(d)
        if pr < 3 and not (2.0 < t < duration - 2.0):
            continue
        if all(abs(t - a) >= gaps[pr] for a, _ in accepted):
            accepted.append((t, pr))
    edges = [0.0] + sorted(t for t, _ in accepted if 0.05 < t < duration - 0.05) + [duration]
    secs = [{"start": r3(a), "end": r3(b)} for a, b in zip(edges[:-1], edges[1:]) if b - a > 0.2]
    for sct in secs:
        sct["kick_density"] = round(density(kicks, beats, sct["start"], sct["end"]), 2)
    return secs


def label_sections(secs: list[dict], y: np.ndarray, rms: np.ndarray, sil: list[dict]) -> list[dict]:
    """energy (0..1), a role (intro/low/mid/high/break/outro) and a letter: sections share a
    letter when timbre (MFCC cos > 0.99), level (< 3 dB) and kick density (< 0.3) all match."""
    import librosa
    peak = rms.max() + 1e-9
    mfcc = librosa.feature.mfcc(y=y, sr=SR, n_mfcc=20, hop_length=2048)
    fps = SR / 2048
    vecs, levels, letters = [], [], []
    for s in secs:
        a = int(s["start"] / ENERGY_HOP)
        b = max(a + 1, int(s["end"] / ENERGY_HOP))
        s["energy"] = round(float(rms[a:b].mean() / peak), 3)
        levels.append(20 * np.log10(rms[a:b].mean() + 1e-9))
        m = mfcc[:, int(s["start"] * fps):max(int(s["start"] * fps) + 1, int(s["end"] * fps))].mean(1)
        vecs.append(m / (np.linalg.norm(m) + 1e-9))
    is_sil = [any(x["start"] <= s["start"] + 0.05 and x["end"] >= s["end"] - 0.05 for x in sil) for s in secs]
    next_letter = 0
    for i, v in enumerate(vecs):
        if is_sil[i]:
            letters.append("break")
            continue
        match = None
        for j in range(i):
            if is_sil[j] or is_sil[i]:
                continue
            if (float(v @ vecs[j]) > 0.99 and abs(levels[i] - levels[j]) < 3
                    and abs(secs[i].get("kick_density", 0) - secs[j].get("kick_density", 0)) < 0.3):
                match = letters[j]
                break
        if match is None:
            match = chr(ord("A") + next_letter % 26)
            next_letter += 1
        letters.append(match)
    energies = np.array([s["energy"] for s, z in zip(secs, is_sil) if not z] or [1.0])
    hi = np.percentile(energies, 75)
    for i, s in enumerate(secs):
        if is_sil[i]:
            role = "break"
        elif i == 0 and s["energy"] < 0.6 * hi:
            role = "intro"
        elif i == len(secs) - 1 and s["energy"] < 0.6 * hi and len(secs) > 2:
            role = "outro"
        elif s["energy"] >= hi and len(secs) > 2:
            role = "high"
        elif s["energy"] < 0.6 * hi:
            role = "low"
        else:
            role = "mid"
        s["label"] = letters[i] if role != "break" else "break"
        s["role"] = role
    return secs


def drops(secs: list[dict], sil: list[dict], dbfs: np.ndarray, on_t: np.ndarray,
          beats: np.ndarray, kicks: list[float]) -> list[float]:
    """A drop is a boundary after which the track is among its loudest parts and either
    (a) the level jumps >= 6 dB (e.g. after a stop), or (b) kicks return after a kick-less
    passage with a >= 3 dB lift. Timed to the first kick (or nearest onset) at the boundary."""
    cands = sorted({s["start"] for s in secs[1:]} | {x["end"] for x in sil})
    lv = np.maximum(dbfs, -80)
    live = lv[lv > -60]
    loud_ref = np.percentile(live, 70) if len(live) else 0
    k = np.asarray(kicks)
    out: list[float] = []
    for t in cands:
        i = int(t / ENERGY_HOP)
        pre, post = lv[max(0, i - 80):i], lv[i:i + 40]   # 4 s before, 2 s after
        if len(pre) < 10 or len(post) < 10 or post.mean() < loud_ref - 3.0:
            continue
        lift = post.mean() - pre.mean()
        kick_return = (len(k) >= 8 and density(k, beats, t - 4.0, t - 0.1) < 0.3
                       and density(k, beats, t - 0.1, t + 4.0) >= 0.6)
        if lift >= 6 or (kick_return and lift >= 3):
            tt = t
            bar = 4 * float(np.median(np.diff(beats))) if len(beats) > 1 else 2.0
            after = k[(k >= t - 0.15) & (k <= t + bar)] if len(k) else k  # first kick within a bar
            if len(after):
                tt = float(after[0])
            elif len(on_t):
                o = on_t[np.argmin(np.abs(on_t - t))]
                if abs(o - t) <= 0.15:
                    tt = float(o)
            if not out or tt - out[-1] > 2.0:
                out.append(r3(tt))
    return out


# -------------------------------------------------------------- tagging ---

def clap_tags(path: Path, rms: np.ndarray, duration: float, topk: int = 5) -> dict:
    import torch
    from transformers import ClapModel, ClapProcessor
    y48 = al.decode(path, 48000, 1)[:, 0]
    win = 10.0
    starts = {0.0}
    if duration > win:
        k = int(np.argmax(np.convolve(rms, np.ones(int(win / ENERGY_HOP)), "valid")))
        starts |= {min(k * ENERGY_HOP, duration - win), max(0.0, duration / 2 - win / 2)}
    clips = [y48[int(s * 48000): int((s + win) * 48000)] for s in sorted(starts)]
    err = None
    for name in CLAP_MODELS:
        try:
            model = ClapModel.from_pretrained(name).eval()
            proc = ClapProcessor.from_pretrained(name)
            break
        except Exception as e:  # noqa: BLE001
            err = e
    else:
        raise RuntimeError(f"no CLAP model loaded: {err}")
    prompts = [f"This is {lab} music." if lab != "spoken word speech" else "This is spoken word speech."
               for lab in CLAP_LABELS]
    with torch.no_grad():
        ti = proc(text=prompts, return_tensors="pt", padding=True)
        t_emb = model.get_text_features(**ti)
        try:
            ai = proc(audio=clips, sampling_rate=48000, return_tensors="pt")
        except TypeError:
            ai = proc(audios=clips, sampling_rate=48000, return_tensors="pt")
        a_emb = model.get_audio_features(**ai)
        t_emb = getattr(t_emb, "pooler_output", t_emb)
        a_emb = getattr(a_emb, "pooler_output", a_emb)
        t_emb = torch.nn.functional.normalize(t_emb, dim=-1)
        a_emb = torch.nn.functional.normalize(a_emb, dim=-1).mean(0, keepdim=True)
        a_emb = torch.nn.functional.normalize(a_emb, dim=-1)
        logits = (a_emb @ t_emb.T)[0] * model.logit_scale_a.exp()
        p = logits.softmax(-1).numpy()
    order = np.argsort(-p)[:topk]
    return {"model": name, "windows": r3l(sorted(starts)),
            "tags": [{"label": CLAP_LABELS[i], "score": round(float(p[i]), 3)} for i in order]}


# ---------------------------------------------------------- hyperframes ---

def hf_crosscheck(path: Path) -> dict:
    import hf
    p = subprocess.run(hf.hf_cmd() + ["audio", str(path), "--only", "kind,bpm,beats,downbeats,sections",
                                      "--quality", "local", "--json"],
                       env=hf.hf_env(), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    d = json.loads(p.stdout)["items"][0]
    return {"kind": (d.get("kind") or {}).get("value"), "bpm": (d.get("bpm") or {}).get("value"),
            "n_beats": len((d.get("beats") or {}).get("times", [])),
            "downbeat_confidence": (d.get("downbeats") or {}).get("confidence"),
            "sections": (d.get("sections") or {}).get("spans"),
            "provenance": d.get("provenance"), "warnings": d.get("warnings")}


# ------------------------------------------------------------------ plot ---

def plot(out: Path, y: np.ndarray, res: dict, rms: np.ndarray) -> None:
    import librosa
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dur = res["duration"]
    w = float(np.clip(dur / 8, 14, 40))
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(w, 8), sharex=True,
                                   gridspec_kw={"height_ratios": [1.1, 1]})
    t = np.arange(len(rms)) * ENERGY_HOP
    ax1.fill_between(t, rms / (rms.max() + 1e-9), color="#4c72b0", alpha=0.55, lw=0)
    palette = ["#fde0c5", "#c5e3fd", "#d5f5c5", "#f5c5e8", "#f5f0c5", "#c5f5f0", "#e0d0ff"]
    letters = sorted({s["label"] for s in res["sections"]})
    for s in res["sections"]:
        c = "#dddddd" if s["label"] == "break" else palette[letters.index(s["label"]) % len(palette)]
        ax1.axvspan(s["start"], s["end"], color=c, alpha=0.6, zorder=0)
        ax1.text((s["start"] + s["end"]) / 2, 1.04, f"{s['label']} · {s['role']}", ha="center",
                 fontsize=9, transform=ax1.get_xaxis_transform())
    for b in res["beats"]:
        ax1.axvline(b, ymin=0, ymax=0.06, color="k", lw=0.6)
    for d in res["downbeats"]:
        ax1.axvline(d, color="k", lw=0.7, alpha=0.35)
    for h in res["hits"]:
        ax1.plot(h["t"], 0.95, "v", color="#d62728", ms=5)
    for d in res["drops"]:
        ax1.axvline(d, color="#d62728", lw=2.2)
        ax1.text(d, 0.85, " DROP", color="#d62728", fontsize=10, fontweight="bold")
    for s in res["silences"]:
        ax1.axvspan(s["start"], s["end"], color="#888", alpha=0.35, hatch="//")
    rel = "reliable" if res["beat_grid_reliable"] else "NOT reliable"
    tags = ", ".join(f"{x['label']} {x['score']:.2f}" for x in res.get("tags", [])[:3])
    ax1.set_title(f"{res['asset_id']}  ·  {res['bpm']} BPM ({rel})  ·  {res['loudness']['I']} LUFS"
                  f"  ·  {tags}", fontsize=11, loc="left", pad=22)
    ax1.set_ylim(0, 1.1)
    ax1.set_ylabel("energy (rel)")
    M = librosa.power_to_db(librosa.feature.melspectrogram(y=y, sr=SR, hop_length=512, n_mels=96), ref=np.max)
    ax2.imshow(M, origin="lower", aspect="auto", extent=[0, len(y) / SR, 0, 96], cmap="magma")
    rows = {"kick": 4, "snare": 40, "hihat": 86}
    for name, yv in rows.items():
        ts = res["onsets"].get(name, [])
        ax2.plot(ts, [yv] * len(ts), "|", color={"kick": "#00e5ff", "snare": "#7CFC00", "hihat": "#ffffff"}[name],
                 ms=9, mew=1.4, label=f"{name} ({len(ts)})")
    ax2.legend(loc="upper right", fontsize=8, framealpha=0.6)
    ax2.set_ylabel("mel")
    ax2.set_xlabel("seconds")
    ax2.set_xlim(0, dur)
    step = 1 if dur <= 40 else 5 if dur <= 200 else 10
    ax2.set_xticks(np.arange(0, dur + 0.01, step))
    fig.tight_layout()
    fig.savefig(out, dpi=90)
    plt.close(fig)


# ------------------------------------------------------------------ main ---

def analyze(path: Path, stems: bool = False, tags: bool = True, hf_check: bool = True,
            fresh: bool = False, quiet: bool = False) -> dict:
    out_dir = assets.analysis_dir(path)
    out_json = out_dir / "audio.json"
    if out_json.exists() and not fresh:
        res = json.loads(out_json.read_text(encoding="utf-8"))
        if res.get("schema") == SCHEMA_VERSION and (not stems or res.get("stems")):
            log(f"cached: {out_json}", quiet)
            return res
    t_start = time.time()
    timings = {}
    log(f"analysing {path.name} -> {out_dir.name}", quiet)
    y = al.decode_mono(path, SR)
    duration = len(y) / SR

    stem_paths = {}
    if stems:
        import separate
        stem_paths = separate.separate(path, quiet=quiet)  # htdemucs: includes a drums stem
    drum_src = al.decode_mono(stem_paths["drums"], SR) if "drums" in stem_paths else y

    t0 = time.time()
    try:
        beats, downbeats, beat_engine = beats_beat_this(y)
    except Exception as e:  # noqa: BLE001
        log(f"  Beat This! failed ({e}); using librosa", quiet)
        beats, downbeats, beat_engine = beats_librosa(y)
    timings["beats"] = round(time.time() - t0, 2)

    t0 = time.time()
    fine, fhop = fine_envelope(y)
    flux = np.maximum(0, np.diff(fine))
    on_t, on_s = onsets_all(y)
    on_refined = refine(on_t, flux, fhop, 0.03)
    dfine, _ = fine_envelope(drum_src)
    bands = band_onsets(drum_src, np.maximum(0, np.diff(dfine)), fhop)
    rms, dbfs = energy_curve(y)
    sil = silences(dbfs, fine, fhop)
    hit_list = hits(on_t, on_s, dbfs, flux, fhop)
    timings["onsets_energy"] = round(time.time() - t0, 2)

    bpm = fit_bpm(beats)
    beats = snap_beats(beats, on_refined)
    downbeats = snap_beats(downbeats, on_refined)
    grid = beat_grid_quality(beats, on_refined, duration)
    t0 = time.time()
    secs = find_sections(y, duration, beats, downbeats, sil, dbfs, bands["kick"])
    secs = label_sections(secs, y, rms, sil)
    drop_list = drops(secs, sil, dbfs, on_refined, beats, bands["kick"])
    timings["sections"] = round(time.time() - t0, 2)


    res: dict = {
        "schema": SCHEMA_VERSION, "asset_id": out_dir.name, "source": str(path.resolve()),
        "duration": r3(duration), "sample_rate": SR,
        "loudness": al.loudness(path),
        "bpm": bpm, "beat_grid_reliable": grid["reliable"], "beat_grid": grid,
        "beat_engine": beat_engine,
        "beats": r3l(beats), "downbeats": r3l(downbeats),
        "onsets": {**bands, "all": r3l(on_refined), "source": "drums stem" if "drums" in stem_paths else "mix"},
        "energy": {"hop": ENERGY_HOP, "unit": "rms relative to track max",
                   "values": [round(float(v), 3) for v in rms / (rms.max() + 1e-9)]},
        "sections": secs, "hits": hit_list, "silences": sil, "drops": drop_list,
        "tags": [], "stems": {k: str(v) for k, v in stem_paths.items()},
    }
    if tags:
        t0 = time.time()
        try:
            c = clap_tags(path, rms, duration)
            res["tags"], res["tags_model"] = c["tags"], c["model"]
        except Exception as e:  # noqa: BLE001
            res["tags_error"] = str(e)
            log(f"  CLAP failed: {e}", quiet)
        timings["tags"] = round(time.time() - t0, 2)
    if hf_check:
        t0 = time.time()
        try:
            res["hyperframes"] = hf_crosscheck(path)
        except Exception as e:  # noqa: BLE001
            res["hyperframes"] = {"error": str(e)}
        timings["hyperframes"] = round(time.time() - t0, 2)
    timings["total"] = round(time.time() - t_start, 2)
    res["timings_s"] = timings
    res["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_json.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    plot(out_dir / "audio.png", y, res, rms)
    log(f"  wrote {out_json} and audio.png ({timings['total']} s)", quiet)
    return res


def summary(res: dict) -> str:
    L = res["loudness"]
    s = [f"{res['asset_id']}: {res['duration']} s | {res['bpm']} BPM "
         f"({'reliable' if res['beat_grid_reliable'] else 'NOT reliable: ' + res['beat_grid']['reason']}) "
         f"| {len(res['beats'])} beats, {len(res['downbeats'])} downbeats",
         f"  loudness I {L['I']} LUFS, LRA {L['LRA']} LU, TP {L['TP']} dBTP",
         f"  onsets: kick {len(res['onsets']['kick'])}, snare {len(res['onsets']['snare'])}, "
         f"hihat {len(res['onsets']['hihat'])}, all {len(res['onsets']['all'])} | hits {len(res['hits'])}",
         "  sections: " + " | ".join(f"{x['start']}-{x['end']} {x['label']}/{x['role']}" for x in res["sections"]),
         f"  drops: {res['drops']} | silences: {[(x['start'], x['end']) for x in res['silences']]}"]
    if res.get("tags"):
        s.append("  tags: " + ", ".join(f"{t['label']} {t['score']}" for t in res["tags"]))
    if res.get("hyperframes") and "bpm" in res["hyperframes"]:
        h = res["hyperframes"]
        s.append(f"  hyperframes: kind {h['kind']}, {h['bpm']} BPM, {h['n_beats']} beats")
    return "\n".join(s)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--stems", action="store_true", help="separate 4 stems first; drum onsets from the drums stem")
    ap.add_argument("--no-tags", action="store_true", help="skip CLAP mood/genre tags")
    ap.add_argument("--no-hf", action="store_true", help="skip the `hyperframes audio` cross-check")
    ap.add_argument("--fresh", action="store_true", help="ignore the cache")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if not a.file.exists():
        sys.exit(f"not found: {a.file}")
    res = analyze(a.file, stems=a.stems, tags=not a.no_tags, hf_check=not a.no_hf, fresh=a.fresh, quiet=a.quiet)
    print(summary(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Sound-effects library: synthesised hits (own work, no licence issues) + indexed packs.

Usage:  uv run tools/sfx.py build                        (synthesise the studio set into library/sfx/synth)
        uv run tools/sfx.py add <file|folder> [--license CC0 --author ... --source URL]
        uv run tools/sfx.py find "whoosh" [--n 5]
        uv run tools/sfx.py list

Synth set (48 kHz stereo, peak -1 dBFS, onset at t=0 unless noted):
  boom, thud, riser (2 s, hits at the END), whoosh, swish (short), impact, hit, braam,
  glitch, flash_pop, drop_808, tape_stop, tick, ding, reverse_swell (1.2 s, peaks at the END),
  epic_hit (trailer drop hit in D major; tools/sfx.py: epic_hit(root, minor) for other keys)
library/sfx/index.json lists every effect with tags, duration, `align` (onset|end: which moment
to place on the anchor) and licence, for tools/build.py and tools/credits.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import audiolib as al  # noqa: E402

SR = al.SR
LIB = cfg.ROOT / "library" / "sfx"
INDEX = LIB / "index.json"
AUDIO_EXT = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


def _t(sec: float) -> np.ndarray:
    return np.arange(int(sec * SR)) / SR


def _st(x: np.ndarray) -> np.ndarray:
    x = x / (np.abs(x).max() + 1e-9) * 0.89
    return np.stack([x, x], 1).astype(np.float32)


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).normal(0, 1, n)


def impact() -> np.ndarray:
    t = _t(1.2)
    body = np.sin(2 * np.pi * np.cumsum(45 + 140 * np.exp(-t * 25)) / SR) * np.exp(-t * 4)
    crack = _noise(len(t), 21) * np.exp(-t * 45) * 0.6
    return _st(np.tanh(1.6 * al._reverb(body + crack, 1.2, 0.2)[: len(t)]))


def hit() -> np.ndarray:
    t = _t(0.45)
    return _st(np.sin(2 * np.pi * np.cumsum(60 + 120 * np.exp(-t * 40)) / SR) * np.exp(-t * 11)
               + _noise(len(t), 3) * np.exp(-t * 80) * 0.4)


def braam() -> np.ndarray:
    t = _t(3.0)
    x = sum(np.sign(np.sin(2 * np.pi * f * t + k)) * a for f, a, k in ((55, 1, 0), (55.4, .8, 1), (110.6, .4, 2), (82.4, .5, 3)))
    x = np.convolve(x, np.ones(60) / 60, mode="same") * np.minimum(1, t / 0.04) * np.exp(-t * 0.9)
    return _st(np.tanh(1.3 * al._reverb(x, 2.0, 0.35)[: len(t)]))


def glitch() -> np.ndarray:
    rng = np.random.default_rng(9)
    t = _t(0.6)
    x = np.zeros(len(t))
    pos = 0
    while pos < len(t):
        seg = int(rng.uniform(0.01, 0.05) * SR)
        f = rng.choice([220, 440, 880, 1760, 3520])
        x[pos:pos + seg] = np.sign(np.sin(2 * np.pi * f * np.arange(min(seg, len(t) - pos)) / SR)) * rng.uniform(.3, 1)
        pos += seg + int(rng.uniform(0, 0.02) * SR)
    return _st(x * np.exp(-t * 3))


def flash_pop() -> np.ndarray:
    t = _t(0.5)
    x = _noise(len(t), 5)
    x = x - np.convolve(x, np.ones(6) / 6, mode="same")
    return _st(x * np.exp(-t * 30) + np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 40) * 0.3)


def drop_808() -> np.ndarray:
    t = _t(1.6)
    return _st(np.tanh(2.2 * np.sin(2 * np.pi * np.cumsum(40 + 55 * np.exp(-t * 5)) / SR) * np.exp(-t * 1.8)))


def tape_stop() -> np.ndarray:
    t = _t(1.0)
    f = 330 * (1 - t) ** 2 + 30
    x = sum(np.sin(2 * np.pi * np.cumsum(f * h) / SR) / h for h in (1, 2, 3))
    return _st(x * (1 - t) ** 0.5)


def tick() -> np.ndarray:
    t = _t(0.06)
    return _st(np.sin(2 * np.pi * 3200 * t) * np.exp(-t * 120))


def ding() -> np.ndarray:
    t = _t(1.4)
    return _st(sum(np.sin(2 * np.pi * f * t) * np.exp(-t * d) * a for f, d, a in ((1318.5, 3, 1), (2637, 5, .4), (3955, 8, .2))))


def swish() -> np.ndarray:
    return al.whoosh(0.35)


NOTE = {"C": 65.41, "C#": 69.30, "D": 73.42, "D#": 77.78, "E": 82.41, "F": 87.31, "F#": 92.50, "G": 98.00,
        "G#": 103.83, "A": 110.00, "A#": 116.54, "B": 123.47}


def epic_hit(root: str = "D", minor: bool = False, length: float = 3.2) -> np.ndarray:
    """Trailer-style 'epic' hit for a drop (bright and big, not a dark sub 'doom'):
    short punchy impact + cymbal crash + detuned brass power chord in the song's key + hall reverb.
    Little energy below 50 Hz on purpose (the music's own drop carries the bass)."""
    from scipy.signal import butter, sosfilt
    t = _t(length)
    n = len(t)
    f0 = NOTE[root]
    # 1. punch: 0.45 s pitch-drop thump (body), no long sub tail
    punch = np.sin(2 * np.pi * np.cumsum(55 + 110 * np.exp(-t * 30)) / SR) * np.exp(-t * 7.5)
    punch += _noise(n, 41) * np.exp(-t * 70) * 0.5                      # transient click
    # 2. crash cymbal: high-passed noise, fast attack, ~2 s shimmer, decorrelated L/R
    hp = butter(4, 3500, "highpass", fs=SR, output="sos")
    crash = np.stack([sosfilt(hp, _noise(n, s)) for s in (51, 52)], 1)
    crash *= (np.exp(-t * 1.6) * np.minimum(1, t / 0.004))[:, None] * 0.16
    # 3. brass power chord (root, fifth, octave, third/minor third an octave up), detuned saws
    third = 1.189 if minor else 1.26
    lp = butter(2, 3200, "lowpass", fs=SR, output="sos")
    brass = np.zeros(n)
    for ratio, amp in ((1, 1.0), (1.5, 0.8), (2, 0.7), (2 * third, 0.45), (3, 0.3)):
        for det in (-0.006, 0.0, 0.0065):
            ph = (t * f0 * 2 * ratio * (1 + det)) % 1.0   # horn range (D3 up), not a muddy D2
            brass += (2 * ph - 1) * amp / 3
    brass = sosfilt(lp, brass)
    brass *= np.minimum(1, t / 0.035) * np.exp(-t * 0.85)
    brass /= np.abs(brass).max() + 1e-9
    # 4. bloom: everything through a hall reverb, brass slightly wider
    mono = 0.8 * punch + 1.3 * brass
    wet = al._reverb(mono, 2.6, 0.32)[:n]
    x = np.stack([wet, wet], 1) + crash
    x[:, 0] += 0.12 * brass                     # small width on the chord
    x[:, 1] -= 0.04 * brass
    hp_lo = butter(2, 45, "highpass", fs=SR, output="sos")
    x = np.stack([sosfilt(hp_lo, x[:, c]) for c in range(2)], 1)
    x = np.tanh(1.2 * x)
    return (x / np.abs(x).max() * 0.89).astype(np.float32)


def reverse_swell() -> np.ndarray:
    x = impact()[::-1].copy()
    return np.ascontiguousarray(x[-int(2.0 * SR):])


SYNTH = {
    "boom": (lambda: al.boom(), "onset", "cinematic sub boom impact trailer drop"),
    "thud": (lambda: al.thud(), "onset", "low thud hit punch"),
    "riser": (lambda: al.riser(), "end", "riser build tension sweep up transition"),
    "whoosh": (lambda: al.whoosh(), "onset", "whoosh swoosh transition air"),
    "swish": (swish, "onset", "swish short whoosh fast cut whip"),
    "impact": (impact, "onset", "impact hit slam cinematic punch"),
    "hit": (hit, "onset", "hit kick punch beat accent"),
    "braam": (braam, "onset", "braam trailer horn brass inception dramatic"),
    "glitch": (glitch, "onset", "glitch digital stutter error"),
    "flash_pop": (flash_pop, "onset", "flash pop camera snap white flash"),
    "drop_808": (drop_808, "onset", "808 bass drop phonk sub"),
    "tape_stop": (tape_stop, "onset", "tape stop slow down record scratch end"),
    "tick": (tick, "onset", "tick click ui pop"),
    "ding": (ding, "onset", "ding bell notification chime"),
    "reverse_swell": (reverse_swell, "end", "reverse swell suck in transition build"),
    "epic_hit": (epic_hit, "onset", "epic trailer hit drop brass crash impact cinematic big"),
}


def load() -> list[dict]:
    return json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []


def save(idx: list[dict]) -> None:
    LIB.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(sorted(idx, key=lambda r: r["name"]), indent=1, ensure_ascii=False), encoding="utf-8")


def build() -> list[dict]:
    out = LIB / "synth"
    out.mkdir(parents=True, exist_ok=True)
    idx = [r for r in load() if r.get("source") != "synth"]
    for name, (fn, align, tags) in SYNTH.items():
        x = fn()
        f = out / f"{name}.wav"
        al.write_wav(f, x, SR)
        idx.append({"name": name, "file": f.relative_to(cfg.ROOT).as_posix(), "duration": round(len(x) / SR, 3),
                    "align": align, "tags": tags.split(), "source": "synth",
                    "license": "own work (ai-video-studio)", "credit": None})
    save(idx)
    return idx


def add(path: Path, meta: dict) -> list[dict]:
    files = sorted(p for p in path.rglob("*") if p.suffix.lower() in AUDIO_EXT) if path.is_dir() else [path]
    idx = load()
    for f in files:
        m = dict(meta)
        side = f.with_suffix(".license.json")
        if side.exists():
            m = {**json.loads(side.read_text(encoding="utf-8")), **{k: v for k, v in meta.items() if v}}
        if not m.get("license"):
            raise SystemExit(f"{f.name}: no licence (--license or a .license.json); refusing")
        dur = len(al.decode_mono(f, 8000)) / 8000
        name = (m.get("title") or f.stem).replace(" ", "_")[:48]
        idx = [r for r in idx if r["file"] != f.resolve().relative_to(cfg.ROOT).as_posix()]
        idx.append({"name": name, "file": f.resolve().relative_to(cfg.ROOT).as_posix(), "duration": round(dur, 3),
                    "align": "onset", "tags": [w.lower() for w in name.replace("_", " ").replace("-", " ").split()],
                    "source": m.get("provider") or "user", "license": m["license"],
                    "credit": f'"{name}" by {m.get("author") or "unknown"}, {m["license"]} ({m.get("page") or m.get("source") or ""})'})
    save(idx)
    return idx


def find(q: str, n: int = 5) -> list[dict]:
    words = q.lower().split()
    scored = [(sum(w in " ".join(r["tags"] + [r["name"]]) for w in words), r) for r in load()]
    return [r for s, r in sorted(scored, key=lambda x: -x[0]) if s > 0][:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    a_ = sub.add_parser("add")
    a_.add_argument("path", type=Path)
    a_.add_argument("--license")
    a_.add_argument("--author")
    a_.add_argument("--source")
    f = sub.add_parser("find")
    f.add_argument("query")
    f.add_argument("--n", type=int, default=5)
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "build":
        idx = build()
        print(f"{sum(1 for r in idx if r['source'] == 'synth')} synth effects -> {LIB / 'synth'}")
    elif a.cmd == "add":
        add(a.path, {"license": a.license, "author": a.author, "source": a.source})
        print(f"{len(load())} effects indexed")
    elif a.cmd == "find":
        for r in find(a.query, a.n):
            print(f"{r['name']:<22} {r['duration']:5.2f}s align={r['align']:<6} {r['license']:<26} {r['file']}")
    else:
        for r in load():
            print(f"{r['name']:<22} {r['duration']:5.2f}s align={r['align']:<6} {r['license']:<26} {r['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Music library: analyse once, find by mood / tempo / length, credit correctly.

Usage:  uv run tools/music_library.py add <file|folder> [--preset incompetech] [--license "CC BY 4.0"]
                                          [--author ...] [--source URL] [--title ...]
        uv run tools/music_library.py find "sad piano" [--bpm 70-100] [--min 30] [--max 180] [--n 5]
        uv run tools/music_library.py list

`add` runs tools/analyze_audio.py (cached) and writes library/music/index.json: title, author,
licence + credit line, duration, bpm (+ whether the beat grid is reliable), musical key,
loudness, CLAP mood tags, sections, drops and a 12-point energy profile. A CLAP audio embedding
per track goes to library/music/embeddings.npz, so `find` ranks tracks by how well a free-text
mood description matches the music (laion/larger_clap_music_and_speech), after the filters.
Tracks without a licence are refused: the studio only uses music it can credit.
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
cfg.model_cache_env()

LIB = cfg.ROOT / "library" / "music"
INDEX, EMB = LIB / "index.json", LIB / "embeddings.npz"
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac"}
PRESETS = {"incompetech": {"author": "Kevin MacLeod", "license": "CC BY 4.0",
                           "license_url": "https://creativecommons.org/licenses/by/4.0/",
                           "source": "https://incompetech.com",
                           "credit": '"{title}" Kevin MacLeod (incompetech.com), licensed under Creative Commons: '
                                     'By Attribution 4.0 License, http://creativecommons.org/licenses/by/4.0/'}}
KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_clap: dict = {}


def clap():
    if not _clap:
        from transformers import ClapModel, ClapProcessor
        name = "laion/larger_clap_music_and_speech"
        _clap["m"], _clap["p"] = ClapModel.from_pretrained(name).eval(), ClapProcessor.from_pretrained(name)
    return _clap["m"], _clap["p"]


def _norm(x):
    x = getattr(x, "pooler_output", x).detach().numpy().astype(np.float32)
    return x / (np.linalg.norm(x, axis=-1, keepdims=True) + 1e-9)


def audio_embedding(path: Path, duration: float) -> np.ndarray:
    import torch
    import audiolib as al
    m, p = clap()
    y = al.decode(path, 48000, 1)[:, 0]
    starts = np.linspace(0, max(0.0, duration - 10), num=min(5, max(1, int(duration // 10))))
    clips = [y[int(s * 48000): int((s + 10) * 48000)] for s in starts]
    with torch.no_grad():
        try:
            inp = p(audio=clips, sampling_rate=48000, return_tensors="pt")
        except TypeError:
            inp = p(audios=clips, sampling_rate=48000, return_tensors="pt")
        e = _norm(m.get_audio_features(**inp)).mean(0)
    return e / (np.linalg.norm(e) + 1e-9)


def text_embedding(text: str) -> np.ndarray:
    import torch
    m, p = clap()
    with torch.no_grad():
        return _norm(m.get_text_features(**p(text=[f"This is {text} music."], return_tensors="pt", padding=True)))[0]


def musical_key(path: Path) -> str:
    """Krumhansl-Schmuckler key estimate from the mean chroma."""
    import librosa
    import audiolib as al
    y = al.decode_mono(path, 22050)
    chroma = librosa.feature.chroma_cqt(y=y, sr=22050).mean(1)
    major = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
    minor = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
    best = max(((np.corrcoef(np.roll(prof, k), chroma)[0, 1], f"{KEYS[k]} {name}")
                for prof, name in ((major, "major"), (minor, "minor")) for k in range(12)))
    return best[1]


def load() -> tuple[list[dict], dict]:
    idx = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else []
    emb = dict(np.load(EMB)) if EMB.exists() else {}
    return idx, emb


def save(idx: list[dict], emb: dict) -> None:
    LIB.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(sorted(idx, key=lambda r: r["title"].lower()), indent=1, ensure_ascii=False),
                     encoding="utf-8")
    np.savez(EMB, **emb)


def add(path: Path, meta: dict) -> dict:
    import analyze_audio
    res = analyze_audio.analyze(path, tags=True, hf_check=False, quiet=True)
    if not meta.get("license"):
        side = path.with_suffix(".license.json")
        if side.exists():  # downloaded with tools/stock.py
            s = json.loads(side.read_text(encoding="utf-8"))
            meta = {**s, **{k: v for k, v in meta.items() if v}}
        else:
            raise SystemExit(f"{path.name}: no licence given (--license / --preset) and no .license.json; refusing")
    title = meta.get("title") or path.stem
    credit = (meta.get("credit") or '"{title}" by {author}, {license} ({source})').format(
        title=title, author=meta.get("author") or "unknown", license=meta["license"],
        source=meta.get("source") or meta.get("page") or "")
    e = np.array(res["energy"]["values"])
    prof = [round(float(x), 2) for x in np.interp(np.linspace(0, len(e) - 1, 12), np.arange(len(e)), e)] if len(e) else []
    rec = {"id": res["asset_id"], "file": path.resolve().relative_to(cfg.ROOT).as_posix() if path.resolve().is_relative_to(cfg.ROOT)
           else str(path.resolve()), "title": title, "author": meta.get("author"), "license": meta["license"],
           "license_url": meta.get("license_url"), "source": meta.get("source") or meta.get("page"), "credit": credit,
           "duration": res["duration"], "bpm": res["bpm"], "beat_grid_reliable": res["beat_grid_reliable"],
           "key": musical_key(path), "loudness_lufs": res["loudness"]["I"],
           "tags": [t["label"] for t in res.get("tags", [])][:5],
           "sections": [{"start": s["start"], "end": s["end"], "role": s["role"]} for s in res["sections"]],
           "drops": res["drops"], "energy_profile": prof}
    idx, emb = load()
    idx = [r for r in idx if r["id"] != rec["id"]] + [rec]
    emb[rec["id"]] = audio_embedding(path, res["duration"])
    save(idx, emb)
    return rec


def find(query: str, bpm: str | None = None, min_d: float = 0, max_d: float = 1e9, n: int = 5) -> list[dict]:
    idx, emb = load()
    lo, hi = (float(x) for x in bpm.split("-")) if bpm else (0, 1e9)
    cand = [r for r in idx if min_d <= r["duration"] <= max_d and (r["bpm"] is None or lo <= r["bpm"] <= hi
                                                                    or lo <= r["bpm"] * 2 <= hi or lo <= r["bpm"] / 2 <= hi)]
    q = text_embedding(query)
    for r in cand:
        r["match"] = round(float(emb[r["id"]] @ q), 3) if r["id"] in emb else -1
    return sorted(cand, key=lambda r: -r["match"])[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_ = sub.add_parser("add")
    a_.add_argument("path", type=Path)
    a_.add_argument("--preset", choices=sorted(PRESETS))
    for k in ("license", "author", "source", "title", "credit", "license_url"):
        a_.add_argument(f"--{k.replace('_', '-')}")
    f = sub.add_parser("find")
    f.add_argument("query")
    f.add_argument("--bpm")
    f.add_argument("--min", type=float, default=0)
    f.add_argument("--max", type=float, default=1e9)
    f.add_argument("--n", type=int, default=5)
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "add":
        files = sorted(p for p in a.path.rglob("*") if p.suffix.lower() in AUDIO_EXT) if a.path.is_dir() else [a.path]
        meta = dict(PRESETS.get(a.preset, {}))
        meta.update({k: getattr(a, k) for k in ("license", "author", "source", "title", "credit", "license_url")
                     if getattr(a, k)})
        for p in files:
            r = add(p, dict(meta))
            print(f"added {r['title']:<28} {r['duration']:6.1f}s {r['bpm']} BPM {r['key']:<9} {', '.join(r['tags'][:3])}")
    elif a.cmd == "find":
        for r in find(a.query, a.bpm, a.min, a.max, a.n):
            print(f"{r['match']:+.3f}  {r['title']:<28} {r['duration']:6.1f}s {r['bpm']} BPM {r['key']:<9} "
                  f"{r['license']:<12} {', '.join(r['tags'][:3])}")
    else:
        idx, _ = load()
        for r in idx:
            print(f"{r['title']:<28} {r['duration']:6.1f}s {r['bpm']} BPM {r['key']:<9} {r['license']:<12} {r['file']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

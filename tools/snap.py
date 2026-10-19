"""Snap planned cut times to musical or spoken anchors: the core of tight sync.

Usage:  uv run tools/snap.py snap analysis/<id>/audio.json 2.0 4.1 6.3 [--to beat|downbeat|kick|onset|hit|drop]
                                  [--tol 0.12] [--offset 12.0]
        uv run tools/snap.py grid analysis/<id>/audio.json --from 0 --to 18 [--every 2] [--on beat]
                                  [--offset 12.0]
        uv run tools/snap.py words analysis/<id>/transcript.json 3.2 7.9 [--edge start|end]

Times are TIMELINE seconds. `--offset` is where the music's 0 s lands minus where you start using
it: if the track is used from 12.0 s in the file and starts at timeline 0, pass --offset 12.0
(anchor_timeline = anchor_file - offset). A snap fails (keeps the planned time, reports `none`)
when no anchor lies within the tolerance. tools/build.py calls snap_time() for every clip with a
`snap` field and records the anchor it used in build.json, so /review can check ±1 frame.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

KINDS = ("beat", "downbeat", "kick", "snare", "onset", "hit", "drop", "section", "word", "word_end")


def anchors(audio: dict | None = None, words: list[dict] | None = None, kind: str = "beat",
            offset: float = 0.0) -> list[float]:
    """Anchor times on the timeline for one kind (music anchors shift by -offset)."""
    out: list[float] = []
    if audio is not None:
        on = audio.get("onsets", {})
        src = {"beat": audio.get("beats", []), "downbeat": audio.get("downbeats", []),
               "kick": on.get("kick", []), "snare": on.get("snare", []), "onset": on.get("all", []),
               "hit": [h["t"] if isinstance(h, dict) else h for h in audio.get("hits", [])],
               "drop": [d["t"] if isinstance(d, dict) else d for d in audio.get("drops", [])],
               "section": [s["start"] for s in audio.get("sections", [])]}.get(kind, [])
        out += [float(t) - offset for t in src]
    if words is not None and kind in ("word", "word_end"):
        out += [float(w["end" if kind == "word_end" else "start"]) for w in words]
    return sorted(out)


def snap_time(t: float, cands: list[float], tol: float) -> tuple[float, float | None]:
    """Nearest anchor within tol -> (snapped time, anchor) else (t, None)."""
    if not cands:
        return t, None
    best = min(cands, key=lambda a: abs(a - t))
    return (best, best) if abs(best - t) <= tol else (t, None)


def frame_round(t: float, fps: float) -> float:
    """Cuts land on frame boundaries: round to the nearest frame start."""
    return round(round(t * fps) / fps, 4)


def grid(audio: dict, t0: float, t1: float, every: int = 1, on: str = "beat", offset: float = 0.0) -> list[float]:
    """Every n-th anchor of a kind between t0 and t1 (timeline seconds)."""
    a = [x for x in anchors(audio, kind=on, offset=offset) if t0 - 1e-6 <= x <= t1 + 1e-6]
    return a[::max(1, every)]


def load_audio(p: Path) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snap")
    s.add_argument("audio", type=Path)
    s.add_argument("times", type=float, nargs="+")
    s.add_argument("--to", default="beat", choices=KINDS)
    s.add_argument("--tol", type=float, default=0.12)
    s.add_argument("--offset", type=float, default=0.0)
    g = sub.add_parser("grid")
    g.add_argument("audio", type=Path)
    g.add_argument("--from", dest="t0", type=float, default=0.0)
    g.add_argument("--to", dest="t1", type=float, required=True)
    g.add_argument("--every", type=int, default=1)
    g.add_argument("--on", default="beat", choices=KINDS)
    g.add_argument("--offset", type=float, default=0.0)
    w = sub.add_parser("words")
    w.add_argument("transcript", type=Path)
    w.add_argument("times", type=float, nargs="+")
    w.add_argument("--edge", default="start", choices=["start", "end"])
    w.add_argument("--tol", type=float, default=0.3)
    a = ap.parse_args()
    if a.cmd == "snap":
        c = anchors(load_audio(a.audio), kind=a.to, offset=a.offset)
        for t in a.times:
            st, anc = snap_time(t, c, a.tol)
            print(f"{t:8.3f} -> {st:8.3f}  " + (f"{a.to} (moved {st - t:+.3f}s)" if anc is not None else "none in tolerance"))
    elif a.cmd == "grid":
        ts = grid(load_audio(a.audio), a.t0, a.t1, a.every, a.on, a.offset)
        print(json.dumps([round(t, 3) for t in ts]))
    else:
        tr = json.loads(a.transcript.read_text(encoding="utf-8"))
        c = anchors(words=tr["words"], kind="word" if a.edge == "start" else "word_end")
        for t in a.times:
            st, anc = snap_time(t, c, a.tol)
            print(f"{t:8.3f} -> {st:8.3f}  " + ("word " + a.edge if anc is not None else "none in tolerance"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

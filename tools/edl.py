"""EDL (edit decision list): load, validate and resolve projects/<slug>/edl.json into a timeline.

Usage:  uv run tools/edl.py projects/<slug>            (validate + print the resolved timeline)
        uv run tools/edl.py projects/<slug> --json     (resolved timeline as JSON)

Schema in docs/CONTRACTS.md ("edl.json"). Resolution rules:
- Clips are sorted by `at` (timeline s). A clip with `snap` moves its `at` to the nearest anchor
  (music beat/downbeat/kick/snare/onset/hit/drop/section, or caption word start/end) within `tol`,
  then every cut is rounded to a frame boundary. The anchor used is recorded per cut.
- A clip lasts until the next clip's `at` (or its own `until`, or the EDL duration).
- An overlapping transition (fade, zoom, whip, any shader) is centred on the cut: it starts
  dur/2 before `at`, so the outgoing clip gets dur/2 of extra footage after the cut and the
  incoming one dur/2 before it. `flash` and `dip` are hard cuts at `at` under an overlay.
- `in` is the source time shown AT the cut (`at`), so handles come from before `in`.
- `speed` (constant) or `ramp` (segments [{dur, speed, rife?}], the last may omit dur) map
  timeline time to source time.
Paths in the EDL are relative to the studio root (or absolute); project-local files may start
with "./" (relative to the project).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import snap  # noqa: E402

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tif", ".tiff"}
SHADERS = {"glitch", "chromatic-split", "cinematic-zoom", "cross-warp-morph", "domain-warp", "flash-through-white",
           "gravitational-lens", "light-leak", "ridged-burn", "ripple-waves", "sdf-iris", "swirl-vortex",
           "thermal-distortion", "whip-pan"}
CSS_TRANSITIONS = {"cut", "fade", "flash", "dip", "zoom", "whip"}
OVERLAP = {"fade", "zoom", "whip"} | SHADERS   # both clips on screen during the transition -> handles
FX = {"zoom_punch", "shake", "push_in", "pull_out", "flash", "scale"}
TOP_KEYS = {"title", "slug", "recipe", "format", "duration", "brand", "grade", "bg", "music", "clips", "flashes",
            "text", "captions", "vo", "sfx", "endcard", "models", "assets", "fonts", "notes", "caption_post",
            "hashtags", "layout", "overlays", "scrim", "fade_out", "poster_at", "highlights"}
FORMATS = {"reels": (1080, 1920), "shorts": (1080, 1920), "feed45": (1080, 1350), "square": (1080, 1080),
           "youtube": (1920, 1080), "whatsapp": (720, 1280)}


class EDLError(ValueError):
    pass


def resolve_path(p: str, project: Path) -> Path:
    if p.startswith("./") or p.startswith(".\\"):
        return (project / p[2:]).resolve()
    q = Path(p)
    return q if q.is_absolute() else (cfg.ROOT / q).resolve()


def load(project: Path) -> dict:
    p = Path(project) / "edl.json"
    if not p.exists():
        raise EDLError(f"{p} not found (run /plan first)")
    return json.loads(p.read_text(encoding="utf-8"))


def fmt(edl: dict) -> tuple[int, int, float]:
    f = edl.get("format", "reels")
    if isinstance(f, str):
        if f not in FORMATS:
            raise EDLError(f"format {f!r}: use one of {sorted(FORMATS)} or {{w,h,fps}}")
        w, h = FORMATS[f]
        return w, h, 30.0
    return int(f["w"]), int(f["h"]), float(f.get("fps", 30))


def validate(edl: dict, project: Path) -> list[str]:
    """Hard errors raise EDLError; soft issues are returned as warnings."""
    warn = [f"unknown top-level key {k!r} (ignored)" for k in edl if k not in TOP_KEYS]
    clips = edl.get("clips", [])
    if not clips:
        raise EDLError("edl.json has no clips")
    ids = set()
    for i, c in enumerate(clips):
        cid = c.get("id") or f"c{i + 1:02d}"
        c.setdefault("id", cid)
        if cid in ids:
            raise EDLError(f"duplicate clip id {cid}")
        ids.add(cid)
        if "src" not in c and "color" not in c:
            raise EDLError(f"clip {cid}: needs `src` (video/photo) or `color` (solid card)")
        if "src" in c and not resolve_path(c["src"], project).exists():
            raise EDLError(f"clip {cid}: source not found: {c['src']}")
        if "at" not in c:
            raise EDLError(f"clip {cid}: needs `at` (timeline seconds)")
        tr = c.get("transition")
        if tr:
            t = tr.get("type", "cut")
            if t not in SHADERS | CSS_TRANSITIONS:
                raise EDLError(f"clip {cid}: transition {t!r}; use {sorted(CSS_TRANSITIONS)} or a shader {sorted(SHADERS)}")
        for f in c.get("fx", []):
            if f.get("type") not in FX:
                raise EDLError(f"clip {cid}: fx {f.get('type')!r}; use {sorted(FX)}")
        if "ramp" in c and "speed" in c:
            warn.append(f"clip {cid}: both `speed` and `ramp`; `ramp` wins")
        if c.get("snap") and c["snap"].get("to") not in snap.KINDS:
            raise EDLError(f"clip {cid}: snap.to must be one of {snap.KINDS}")
    m = edl.get("music")
    if m and not resolve_path(m["src"], project).exists():
        raise EDLError(f"music not found: {m['src']}")
    for s in edl.get("sfx", []):
        if "name" not in s and "src" not in s:
            raise EDLError("sfx entries need `name` (library/sfx) or `src`")
    for t in edl.get("text", []):
        if not {"content", "at"} <= set(t):
            raise EDLError(f"text entries need `content` and `at`: {t}")
    return warn


def music_offset(edl: dict) -> float:
    m = edl.get("music") or {}
    return float(m.get("from", 0.0)) - float(m.get("at", 0.0))


def segments(c: dict, length: float) -> list[dict]:
    """Timeline segments [{dur, speed, rife}] covering `length` seconds."""
    if c.get("ramp"):
        segs, used = [], 0.0
        for k, s in enumerate(c["ramp"]):
            d = s.get("dur")
            if d is None or k == len(c["ramp"]) - 1:
                d = length - used if d is None else d
            segs.append({"dur": float(d), "speed": float(s.get("speed", 1.0)), "rife": bool(s.get("rife", False))})
            used += float(d)
        diff = length - sum(s["dur"] for s in segs)
        segs[-1]["dur"] += diff  # the last segment absorbs rounding / snapping changes
        if segs[-1]["dur"] <= 0:
            raise EDLError(f"clip {c['id']}: ramp segments are longer than the clip ({length:.3f}s)")
        return segs
    return [{"dur": length, "speed": float(c.get("speed", 1.0)), "rife": bool(c.get("rife", False))}]


def resolve(edl: dict, project: Path, audio: dict | None = None, words: list[dict] | None = None) -> dict:
    """-> timeline dict (see module doc). `audio` = the music's audio.json, `words` = caption words
    on the timeline (for word snapping)."""
    W, H, fps = fmt(edl)
    off = music_offset(edl)
    clips = sorted((dict(c) for c in edl["clips"]), key=lambda c: float(c["at"]))
    cuts = []
    for c in clips:
        at = float(c["at"])
        planned = at
        anchor = None
        sn = c.get("snap")
        if sn:
            kind = sn.get("to", "beat")
            cands = snap.anchors(audio, words, kind, off) if kind not in ("word", "word_end") else \
                snap.anchors(None, words, kind)
            at, anchor = snap.snap_time(at, cands, float(sn.get("tol", 0.12)))
        c["at"] = snap.frame_round(at, fps)
        cuts.append({"clip": c["id"], "planned": planned, "t": c["at"], "anchor": anchor,
                     "kind": (sn or {}).get("to") if anchor is not None else None})
    clips.sort(key=lambda c: c["at"])
    for a, b in zip(clips, clips[1:]):
        if b["at"] - a["at"] < 1 / fps:
            raise EDLError(f"clips {a['id']} and {b['id']} land on the same frame after snapping")
    ends = [c["at"] for c in clips[1:]]
    last_end = float(clips[-1].get("until") or edl.get("duration") or 0)
    if not last_end:
        raise EDLError("set `duration` (or `until` on the last clip)")
    ends.append(last_end)
    duration = float(edl.get("duration") or last_end)
    out = []
    for i, (c, end) in enumerate(zip(clips, ends)):
        until = snap.frame_round(float(c.get("until", end)), fps)
        tr = c.get("transition") or {"type": "cut"}
        if i == 0:
            tr = {"type": "cut"}
        d_in = 0.0 if tr.get("type", "cut") == "cut" else float(tr.get("dur", 0.4))
        nxt = clips[i + 1].get("transition") if i + 1 < len(clips) else None
        d_out = float(nxt.get("dur", 0.4)) if nxt and nxt.get("type", "cut") in OVERLAP else 0.0
        pre = d_in / 2 if tr.get("type", "cut") in OVERLAP else 0.0
        post = d_out / 2
        segs = segments(c, until - c["at"])
        segs[0]["dur"] += pre
        segs[-1]["dur"] += post
        src_in = None
        if "src" in c:
            src_in = float(c.get("in", 0.0)) - pre * segs[0]["speed"]
            if src_in < 0:
                src_in = 0.0
        src_len = sum(s["dur"] * s["speed"] for s in segs)
        p = resolve_path(c["src"], project) if "src" in c else None
        kind = "color" if p is None else ("photo" if p.suffix.lower() in PHOTO_EXT else "video")
        out.append({**c, "kind": kind, "path": str(p) if p else None, "at": c["at"], "until": until,
                    "tl_start": round(c["at"] - pre, 4), "tl_end": round(until + post, 4),
                    "transition": {"type": tr.get("type", "cut"), "dur": d_in},
                    "src_in": None if src_in is None else round(src_in, 4),
                    "src_out": None if src_in is None else round(src_in + src_len, 4), "segments": segs})
    shader = any(c["transition"]["type"] in SHADERS for c in out)
    return {"w": W, "h": H, "fps": fps, "duration": duration, "music_offset": off, "clips": out, "cuts": cuts,
            "shader_mode": shader}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    edl = load(a.project)
    for w in validate(edl, a.project):
        print("warning:", w)
    audio = None
    if edl.get("music"):
        import analyze_audio
        audio = analyze_audio.analyze(resolve_path(edl["music"]["src"], a.project), tags=False, hf_check=False, quiet=True)
    tl = resolve(edl, a.project, audio)
    if a.json:
        print(json.dumps(tl, indent=1, ensure_ascii=False))
        return 0
    print(f"{tl['w']}x{tl['h']} @ {tl['fps']} fps, {tl['duration']} s, shader mode: {tl['shader_mode']}")
    cut = {k["clip"]: k for k in tl["cuts"]}
    for c in tl["clips"]:
        k = cut[c["id"]]
        anc = f"snapped to {k['kind']} ({k['t'] - k['planned']:+.3f}s)" if k["anchor"] is not None else "unsnapped"
        sp = "/".join(f"{s['speed']:g}x" for s in c["segments"])
        print(f"  {c['id']:<5} {c['kind']:<5} {c['at']:7.3f}-{c['until']:7.3f}  in {c['transition']['type']:<12}"
              f" speed {sp:<10} {anc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

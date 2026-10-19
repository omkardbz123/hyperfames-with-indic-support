"""Footage and photo preparation for a build: one finished, silent clip per EDL clip.

Used by tools/build.py (no CLI of its own besides a self-test):
  prep_video(clip, tl, project)  -> assets/clips/<id>_<key>.mp4  (canvas size, fps, graded,
                                    speed/ramp applied with RIFE where asked, keyframe every second)
  prep_photo(clip, tl, project)  -> assets/photos/<id>_<key>.jpg (cover-cropped around the focus
                                    point, with Ken Burns headroom, graded)
  prep_audio(clip, project)      -> assets/audio/<id>_<key>.wav  (the clip's own sound, speed 1 parts)
Outputs are cached by a hash of the inputs; a re-build only redoes what changed.

Reframe (`crop`): "center" (default), {"x": 0.3, "y": 0.5} focus (0..1), or "track" (smoothed
subject path from tools/track_subject.py, applied per frame with sendcmd).
Grade (`grade`): a LUT name from library/luts ("none" to skip); the EDL `grade` is the default.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

VERSION = 6  # bump to invalidate every cached prep output
LUTS = cfg.ROOT / "library" / "luts"


def _key(*parts) -> str:
    h = hashlib.sha1()
    for p in parts:
        if isinstance(p, Path) and p.exists():
            st = p.stat()
            h.update(f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}".encode())
        else:
            h.update(json.dumps(p, sort_keys=True, default=str).encode())
    return h.hexdigest()[:10]


def _workdir(name: str) -> Path:
    d = cfg.path("cache") / "build_tmp" / name
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)  # our own scratch under cache/
    d.mkdir(parents=True)
    return d


def _ff(args: list[str], cwd: Path | None = None) -> None:
    r = subprocess.run([cfg.ffmpeg(), "-hide_banner", "-y", "-v", "error", *args], cwd=cwd,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(f"ffmpeg failed: {r.stderr.strip()[-800:]}")


def probe(path: Path) -> dict:
    import fx
    return fx.probe(path)


def grade_name(clip: dict, edl: dict) -> str | None:
    g = clip.get("grade", edl.get("grade"))
    return None if not g or g == "none" else g


def _lut_into(wd: Path, name: str | None) -> str | None:
    """Copy the LUT next to the job so the filter can use a plain relative filename (no drive colon)."""
    if not name:
        return None
    src = LUTS / f"{name}.cube"
    if not src.exists():
        raise SystemExit(f"LUT {name!r} not in library/luts ({', '.join(p.stem for p in LUTS.glob('*.cube'))})")
    shutil.copy(src, wd / "grade.cube")
    return "lut3d=file=grade.cube:interp=tetrahedral"


def crop_box(src_w: int, src_h: int, W: int, H: int, focus: tuple[float, float] = (0.5, 0.5),
             zoom: float = 1.0) -> tuple[int, int, int, int]:
    """Largest W:H box inside the source around a focus point, divided by zoom (>1 = tighter on the
    focus, real pixels instead of a CSS scale) -> (cw, ch, x, y), even sizes."""
    if src_w / src_h > W / H:
        ch = src_h - src_h % 2
        cw = int(round(ch * W / H / 2) * 2)
    else:
        cw = src_w - src_w % 2
        ch = int(round(cw * H / W / 2) * 2)
    if zoom > 1:
        cw, ch = int(round(cw / zoom / 2) * 2), int(round(ch / zoom / 2) * 2)
    x = int(min(max(focus[0] * src_w - cw / 2, 0), src_w - cw))
    y = int(min(max(focus[1] * src_h - ch / 2, 0), src_h - ch))
    return cw, ch, x, y


def prep_video(clip: dict, tl: dict, edl: dict, project: Path) -> Path:
    import fx
    src = Path(clip["path"])
    W, H, fps = tl["w"], tl["h"], tl["fps"]
    g = grade_name(clip, edl)
    crop = clip.get("crop", "center")
    key = _key(VERSION, src, clip["src_in"], clip["segments"], W, H, fps, g, crop, clip.get("stabilize"))
    out = project / "assets" / "clips" / f"{clip['id']}_{key}.mp4"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    for old in out.parent.glob(f"{clip['id']}_*.mp4"):
        _trash(old, project)
    info = probe(src)
    sw, sh = info["w"], info["h"]
    wd = _workdir(f"{project.name}_{clip['id']}")
    lut = _lut_into(wd, g)
    track = None
    if crop == "track":
        import track_subject
        aw, ah = W // math.gcd(W, H), H // math.gcd(W, H)
        track = track_subject.track(src, aspect=f"{aw}:{ah}", quiet=True)
        cw, ch = track["crop"]
        x0, y0 = track["path"][0]["x"], track["path"][0]["y"]
    else:
        foc = (crop.get("x", 0.5), crop.get("y", 0.5)) if isinstance(crop, dict) else (0.5, 0.5)
        cw, ch, x0, y0 = crop_box(sw, sh, W, H, foc, float(crop.get("zoom", 1.0)) if isinstance(crop, dict) else 1.0)
    parts = []
    s_t = clip["src_in"]
    for k, seg in enumerate(clip["segments"]):
        s_len = seg["dur"] * seg["speed"]
        part = wd / f"seg{k}.mp4"
        inp, ss, tlen, tmul = src, s_t, s_len, 1.0
        if seg["rife"] and seg["speed"] < 1:
            factor = max(2, math.ceil(1 / seg["speed"] - 1e-6))
            slow = wd / f"rife{k}.mp4"
            fx.slowmo(src, slow, factor=factor, start=s_t, end=s_t + s_len)
            inp, ss, tlen, tmul = slow, 0.0, None, float(factor)
            pts = (1 / seg["speed"]) / factor
        else:
            pts = 1 / seg["speed"]
        chain = []
        if track is not None:
            lines, last = [], None
            for p in track["path"]:
                if s_t - 1 / fps <= p["t"] <= s_t + s_len + 1 / fps and p["x"] != last:
                    lines.append(f"{max(0.0, (p['t'] - s_t) * tmul):.4f} crop@c x {p['x']};")
                    last = p["x"]
            (wd / f"seg{k}.cmd").write_text("\n".join(lines) + "\n", encoding="utf-8")
            first = next((p for p in track["path"] if p["t"] >= s_t), track["path"][0])
            chain += [f"sendcmd=f=seg{k}.cmd", f"crop@c=w={cw}:h={ch}:x={first['x']}:y={y0}"]
        else:
            chain.append(f"crop={cw}:{ch}:{x0}:{y0}")
        chain.append(f"scale={W}:{H}:flags=lanczos")
        if abs(pts - 1) > 1e-4:
            chain.append(f"setpts={pts:.6f}*PTS")
        chain.append(f"fps={fps:g}")
        chain.append("tpad=stop_mode=clone:stop_duration=12")  # holds the last frame if the clip must run longer; -frames:v trims
        if lut:
            chain.append(lut)
        chain += ["setsar=1", "format=yuv420p"]
        args = []
        if ss:
            args += ["-ss", f"{ss:.4f}"]
        if tlen is not None:
            args += ["-t", f"{tlen:.4f}"]
        args += ["-i", str(inp.resolve()), "-an", "-vf", ",".join(chain), "-frames:v",
                 str(max(1, round(seg["dur"] * fps))), *ENC(fps), str(part.resolve())]
        _ff(args, cwd=wd)
        parts.append(part)
        s_t += s_len
    if len(parts) == 1:
        shutil.move(str(parts[0]), str(out))
    else:
        (wd / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
        _ff(["-f", "concat", "-safe", "0", "-i", "list.txt", *ENC(fps), str(out.resolve())], cwd=wd)
    shutil.rmtree(wd, ignore_errors=True)
    return out


def ENC(fps: float) -> list[str]:
    g = str(int(round(fps)))
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-g", g,
            "-keyint_min", g, "-sc_threshold", "0", "-movflags", "+faststart"]


def prep_photo(clip: dict, tl: dict, edl: dict, project: Path) -> Path:
    from PIL import Image, ImageOps
    src = Path(clip["path"])
    W, H = tl["w"], tl["h"]
    g = grade_name(clip, edl)
    kb = clip.get("kenburns") or {}
    zmax = max(float(kb.get("from", 1.0)), float(kb.get("to", 1.08)), 1.0)
    focus = kb.get("focus")
    if focus is None:
        import analyze_photos
        focus = analyze_photos.analyse_one(src).get("focus") or [0.5, 0.5]
    key = _key(VERSION, src, W, H, g, zmax, focus)
    out = project / "assets" / "photos" / f"{clip['id']}_{key}.jpg"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    for old in out.parent.glob(f"{clip['id']}_*.jpg"):
        _trash(old, project)
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    cw, ch, x, y = crop_box(im.width, im.height, W, H, tuple(focus))
    im = im.crop((x, y, x + cw, y + ch))
    tw, th = int(W * zmax), int(H * zmax)
    clip["upscaled"] = cw < tw
    im = im.resize((tw, th), Image.LANCZOS)
    wd = _workdir(f"{project.name}_{clip['id']}")
    im.save(wd / "in.png")
    lut = _lut_into(wd, g)
    _ff(["-i", "in.png", *(["-vf", lut] if lut else []), "-q:v", "2", str(out.resolve())], cwd=wd)
    shutil.rmtree(wd, ignore_errors=True)
    clip["focus"] = focus
    return out


def prep_audio(clip: dict, project: Path) -> Path | None:
    """The clip's own sound for speed-1 segments (others are silent), as a 48 kHz stereo wav."""
    import audiolib as al
    import numpy as np
    src = Path(clip["path"])
    if not probe(src)["audio"]:
        return None
    key = _key(VERSION, src, clip["src_in"], clip["segments"])
    out = project / "assets" / "audio" / f"{clip['id']}_{key}.wav"
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    full = al.decode(src, al.SR, 2)
    pieces, s_t = [], clip["src_in"]
    for seg in clip["segments"]:
        n = int(round(seg["dur"] * al.SR))
        s_len = seg["dur"] * seg["speed"]
        if abs(seg["speed"] - 1) < 1e-3:
            a = full[int(s_t * al.SR): int(s_t * al.SR) + n]
            a = np.pad(a, ((0, n - len(a)), (0, 0)))
        else:
            a = np.zeros((n, 2), np.float32)
        pieces.append(a)
        s_t += s_len
    y = np.concatenate(pieces)
    fade = min(len(y) // 2, int(0.012 * al.SR))  # no clicks at the cut
    if fade:
        ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
        y[:fade] *= ramp
        y[-fade:] *= ramp[::-1]
    al.write_wav(out, y, al.SR)
    return out


def _trash(p: Path, project: Path) -> None:
    """Superseded prep output -> _trash/<project>/ (never deleted outright)."""
    d = cfg.ROOT / "_trash" / project.name / p.parent.name
    d.mkdir(parents=True, exist_ok=True)
    shutil.move(str(p), str(d / p.name))

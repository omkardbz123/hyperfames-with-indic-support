"""Ingest: register raw files for a project, make awkward formats usable, record licences.

Usage:  uv run tools/ingest.py [files or folders ...] --project projects/<slug>
                               [--own --author "Name"] [--license "CC BY 4.0" --author ... --source URL]
                               [--move]
        (no files: everything in inbox/)

Per file:
- asset id (sha1-8 + name) and a probe: kind (video/audio/photo), size, fps, duration, codecs
- awkward formats get a usable copy in analysis/<id>/: variable-frame-rate video -> CFR H.264
  (`cfr.mp4`, keyframe every second), HEIC/AVIF photos -> JPEG (EXIF-upright)
- licence: `--own` writes <file>.license.json = own footage of the user (ask the user first!);
  `--license` records a third-party licence. Files without a licence are listed so credits.py
  can't fail later by surprise.
- projects/<slug>/assets.json lists every file with its id, kind, usable path and licence.
--move moves files from inbox/ into projects/<slug>/media/ (default: they stay where they are).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import assets  # noqa: E402

VIDEO = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts", ".3gp"}
AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}
PHOTO = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif", ".bmp", ".tif", ".tiff"}


def probe(p: Path) -> dict:
    out = subprocess.run([cfg.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(p)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    return json.loads(out or "{}")


def kind_of(p: Path) -> str | None:
    s = p.suffix.lower()
    return "video" if s in VIDEO else "audio" if s in AUDIO else "photo" if s in PHOTO else None


def make_usable(p: Path, kind: str, info: dict) -> tuple[Path, list[str]]:
    notes = []
    d = assets.analysis_dir(p)
    if kind == "video":
        v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
        r, avg = v.get("r_frame_rate", "0/1"), v.get("avg_frame_rate", "0/1")
        frac = lambda x: (lambda n, m: n / m if m else 0)(*map(float, x.split("/")))  # noqa: E731
        vfr = abs(frac(r) - frac(avg)) > 0.01 * max(frac(r), 1)
        odd = v.get("codec_name") not in ("h264", "hevc", "vp9", "av1", "prores", "mpeg4")
        if vfr or odd:
            fps = round(frac(avg)) or 30
            out = d / "cfr.mp4"
            if not out.exists():
                subprocess.run([cfg.ffmpeg(), "-v", "error", "-y", "-i", str(p), "-vf", f"fps={fps}", "-c:v", "libx264",
                                "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p", "-g", str(fps),
                                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True)
            notes.append(f"{'variable frame rate' if vfr else v.get('codec_name')} -> CFR H.264 {fps} fps copy")
            return out, notes
    if kind == "photo" and p.suffix.lower() in (".heic", ".heif", ".avif"):
        out = d / "photo.jpg"
        if not out.exists():
            from PIL import Image, ImageOps
            try:
                import pillow_heif  # type: ignore
                pillow_heif.register_heif_opener()
            except ImportError:
                notes.append("HEIC needs pillow-heif (not installed); convert on the phone or ask to install it")
                return p, notes
            ImageOps.exif_transpose(Image.open(p)).convert("RGB").save(out, quality=95)
        notes.append("HEIC/AVIF -> JPEG copy")
        return out, notes
    return p, notes


def licence_of(p: Path) -> dict | None:
    for side in (p.with_suffix(".license.json"), p.parent / f"{p.stem}.license.json"):
        if side.exists():
            return json.loads(side.read_text(encoding="utf-8"))
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--own", action="store_true", help="the user confirmed they own these files")
    ap.add_argument("--license")
    ap.add_argument("--author")
    ap.add_argument("--source")
    ap.add_argument("--move", action="store_true")
    a = ap.parse_args()
    paths = a.paths or [cfg.ROOT / "inbox"]
    files = []
    for p in paths:
        files += sorted(x for x in p.rglob("*") if x.is_file() and kind_of(x)) if p.is_dir() else [p]
    proj = a.project.resolve()
    proj.mkdir(parents=True, exist_ok=True)
    reg_p = proj / "assets.json"
    reg = {r["id"]: r for r in (json.loads(reg_p.read_text(encoding="utf-8")) if reg_p.exists() else [])}
    for f in files:
        k = kind_of(f)
        if not k:
            print(f"skip {f.name}: unknown type")
            continue
        if a.move and (cfg.ROOT / "inbox") in f.resolve().parents:
            dst = proj / "media" / f.name
            dst.parent.mkdir(exist_ok=True)
            shutil.move(str(f), str(dst))
            side = f.with_suffix(".license.json")
            if side.exists():
                shutil.move(str(side), str(dst.with_suffix(".license.json")))
            f = dst
        info = probe(f)
        usable, notes = make_usable(f, k, info)
        lic = licence_of(f)
        if a.own or a.license:
            lic = {"title": f.stem, "author": a.author or ("the user" if a.own else None),
                   "license": "own footage (user)" if a.own else a.license, "source": a.source,
                   "kind": k, "recorded": time.strftime("%Y-%m-%d")}
            f.with_suffix(".license.json").write_text(json.dumps(lic, indent=1, ensure_ascii=False), encoding="utf-8")
        aid = assets.asset_id(f)
        fmt = info.get("format", {})
        v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
        reg[aid] = {"id": aid, "file": str(f.resolve()), "usable": str(Path(usable).resolve()), "kind": k,
                    "duration": round(float(fmt.get("duration", 0) or 0), 3),
                    "size": [v.get("width"), v.get("height")] if v else None, "codec": v.get("codec_name"),
                    "license": (lic or {}).get("license"), "notes": notes}
        print(f"{aid:<40} {k:<6} {reg[aid]['duration']:7.2f}s {str(reg[aid]['size']):<14} "
              f"licence: {reg[aid]['license'] or 'MISSING'}  {'; '.join(notes)}")
    reg_p.write_text(json.dumps(sorted(reg.values(), key=lambda r: r["file"]), indent=1, ensure_ascii=False), encoding="utf-8")
    missing = [r for r in reg.values() if not r["license"]]
    if missing:
        print(f"\n{len(missing)} file(s) without a licence: ask the user whether they own them "
              f"(then --own) or where they came from (--license/--author/--source).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

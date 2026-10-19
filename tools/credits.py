"""Credits for a video: every third-party asset with its licence, plus a caption credit line.

Usage:  uv run tools/credits.py <project dir> [--out exports/<slug>] [--allow-unknown]
        uv run tools/credits.py --files a.mp3 b.jpg ... [--models indic-flex,mms,edge-tts]

Licence sources, in order: <file>.license.json beside the file (tools/stock.py writes these),
library/music/index.json, library/sfx/index.json, library/fonts/index.json, then
<file stem>.license.json. Own work (synth SFX, generated LUTs, VO from our scripts) is listed
as such. Models whose licence asks for attribution are credited when the project used them
(from edl.json "models"). An asset with no licence makes this fail (BUILD_PLAN §2.7, §14),
unless --allow-unknown. Writes CREDITS.txt and caption.txt (short line) when --out is given.
CC BY-SA content means the video should be shared under CC BY-SA terms with credit: noted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

MODELS = {
    "indic-flex": "Speech recognition: Built with Indic-Transcribe-Flex from Bodhan AI / AI4Bharat "
                  "(Indic Open Model License v1.0); base model Canary-1B-v2 by NVIDIA (CC BY 4.0).",
    "indic-core": "Speech recognition: Built with Indic-Transcribe-Core from Bodhan AI / AI4Bharat "
                  "(Indic Open Model License v1.0); base model Canary-1B-v2 by NVIDIA (CC BY 4.0).",
    "mms": "Word timing: MMS-300m forced aligner (Meta AI / MahmoudAshraf97, CC BY-NC 4.0).",
    "parakeet": "English speech recognition: NVIDIA Parakeet TDT 0.6B v3 (CC BY 4.0).",
    "edge-tts": "Voiceover: synthetic voices (Microsoft neural TTS via edge-tts).",
    "kokoro": "Voiceover: Kokoro-82M (Apache 2.0).",
    "rife": "Slow motion: RIFE (Practical-RIFE, MIT) via rife-ncnn-vulkan.",
    "realesrgan": "Upscaling: Real-ESRGAN (BSD-3-Clause).",
    "htdemucs": "Stem separation: Demucs (Meta, MIT) via audio-separator.",
    "gemini": "Review assistance: Gemini 3.8 Flash via Google Antigravity (no generated media used).",
}


def _index(name: str) -> dict[str, dict]:
    p = cfg.ROOT / "library" / name / "index.json"
    if not p.exists():
        return {}
    rows = json.loads(p.read_text(encoding="utf-8"))
    return {str((cfg.ROOT / r["file"]).resolve()).lower(): r for r in rows if "file" in r}


def lookup(path: Path, music: dict, sfx: dict) -> dict | None:
    key = str(path.resolve()).lower()
    if key in music:  # the library indexes know what the file is used as
        r = music[key]
        return {"kind": "music", "title": r["title"], "author": r.get("author"), "license": r["license"],
                "url": r.get("source"), "credit": r.get("credit")}
    if key in sfx:
        r = sfx[key]
        return {"kind": "sfx", "title": r["name"], "author": r.get("author"), "license": r["license"],
                "url": None, "credit": r.get("credit")}
    for side in (path.with_suffix(".license.json"), path.parent / f"{path.stem}.license.json"):
        if side.exists():
            m = json.loads(side.read_text(encoding="utf-8"))
            kind = {"audio": "music"}.get(m.get("kind"), m.get("kind", "media"))
            return {"kind": kind, "title": m.get("title") or path.stem, "author": m.get("author"),
                    "license": m.get("license"), "url": m.get("page") or m.get("source") or m.get("url"),
                    "credit": m.get("credit")}
    if "luts" in path.parts or path.suffix == ".cube":
        return {"kind": "look", "title": path.stem, "author": None, "license": "own work (ai-video-studio)",
                "url": None, "credit": None}
    return None


def _short_lic(lic: str | None) -> str:
    """Caption-friendly licence: long internal permission notes become "used with permission"."""
    low = (lic or "").lower()
    return "used with permission" if low.startswith(("provided by", "used with permission")) else (lic or "unknown")


def build(files: list[Path], models: list[str], fonts: list[str], title: str,
          allow_unknown: bool = False) -> tuple[str, str, list[str]]:
    music, sfx = _index("music"), _index("sfx")
    seen, rows, unknown = set(), [], []
    for f in files:
        if str(f.resolve()).lower() in seen:
            continue
        seen.add(str(f.resolve()).lower())
        m = lookup(f, music, sfx)
        if m is None or not m.get("license"):
            unknown.append(str(f))
            continue
        rows.append(m)
    if unknown and not allow_unknown:
        raise SystemExit("unknown licence for:\n  " + "\n  ".join(unknown) +
                         "\nadd a <file>.license.json (title, author, license, page) or pass --allow-unknown")
    own = [r for r in rows if "own work" in (r["license"] or "")]
    third = [r for r in rows if r not in own]

    def line(r):
        if r.get("credit"):
            return f"- {r['credit']}"
        by = f" by {r['author']}" if r.get("author") else ""
        url = f", {r['url']}" if r.get("url") else ""
        return f"- \"{r['title']}\"{by} ({r['license']}){url}"

    groups = {"Music": "music", "Footage & photos": None, "Sound effects": "sfx"}
    out = [f"CREDITS - {title}", ""]
    for head, kind in groups.items():
        sel = [r for r in third if (r["kind"] == kind if kind else r["kind"] not in ("music", "sfx"))]
        if sel:
            out += [head, *[line(r) for r in sel], ""]
    if fonts:
        out += ["Fonts (SIL Open Font License): " + ", ".join(sorted(set(fonts))), ""]
    used = [MODELS[m] for m in models if m in MODELS]
    if used:
        out += ["Made with free / open tools", *[f"- {u}" for u in used], ""]
    if own:
        out += ["Own work: " + ", ".join(sorted({r['title'] for r in own})), ""]
    if any("SA" in (r["license"] or "").upper().replace("-", " ").split() or "BY-SA" in (r["license"] or "").upper()
           for r in third):
        out += ["Note: CC BY-SA material is included, so share this video under CC BY-SA 4.0 with the credits above.", ""]
    if unknown:
        out += ["UNKNOWN LICENCE (check before posting): " + ", ".join(unknown), ""]
    # short caption line: music first (CC BY requires it in the post), then others
    mus = [r for r in third if r["kind"] == "music"]
    short = []
    if mus:
        def mline(r):
            au = (r.get("author") or "unknown").strip()
            if au.lower().startswith("provided by"):  # permission-based: "courtesy of <org>"
                return f"\"{r['title']}\" (courtesy of {au[len('provided by'):].strip()})"
            return f"\"{r['title']}\" by {au} ({_short_lic(r['license'])})"
        short.append("Music: " + "; ".join(mline(r) for r in mus))
    oth = [r for r in third if r["kind"] not in ("music", "sfx")]
    if oth:
        # long internal notes ("provided by X via the user ...") read as "used with permission" in a post
        lic = sorted({_short_lic(r["license"]) for r in oth})
        authors = sorted({(r.get("author") or "unknown").split(" (")[0].split(",")[0].strip()[:40] for r in oth})
        short.append(f"Images/footage: {', '.join(authors[:4])}{' et al.' if len(authors) > 4 else ''} ({', '.join(lic)})")
    if any(m.startswith("indic") for m in models):
        short.append("Captions: Indic-Transcribe (Bodhan AI / AI4Bharat)")
    caption = " · ".join(short) + (" · Full credits in comments." if third else "")
    return "\n".join(out).rstrip() + "\n", caption, unknown


def from_project(project: Path) -> tuple[list[Path], list[str], list[str], str]:
    """build.json (written by tools/build.py: every asset, font and model actually used) if present,
    else the EDL's own `assets`/`models`/`fonts` lists."""
    bj = project / "build.json"
    edl = json.loads((bj if bj.exists() else project / "edl.json").read_text(encoding="utf-8"))
    files = [Path(a["path"]) if Path(a["path"]).is_absolute() else cfg.ROOT / a["path"] for a in edl.get("assets", [])]
    return files, edl.get("models", []), edl.get("fonts", []), edl.get("title", project.name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", nargs="?", type=Path)
    ap.add_argument("--files", nargs="*", type=Path, default=[])
    ap.add_argument("--models", default="")
    ap.add_argument("--fonts", default="")
    ap.add_argument("--title", default="video")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--allow-unknown", action="store_true")
    a = ap.parse_args()
    if a.project:
        files, models, fonts, title = from_project(a.project)
    else:
        files, models, fonts, title = a.files, [m for m in a.models.split(",") if m], \
            [f for f in a.fonts.split(",") if f], a.title
    text, caption, _ = build(files, models, fonts, title, a.allow_unknown)
    print(text)
    print("caption line:\n" + caption)
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "CREDITS.txt").write_text(text, encoding="utf-8")
        (a.out / "caption_credit.txt").write_text(caption + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

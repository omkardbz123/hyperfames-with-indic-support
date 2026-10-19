"""Index footage and photos for text search (SigLIP 2 embeddings, cached per asset).

Usage:  uv run tools/index_footage.py <file|folder> [...] [--every 1.0] [--fresh]

Videos: runs tools/analyze_video.py (shots) if needed, then embeds a frame every `--every`
seconds plus each shot's best frame -> analysis/<asset-id>/siglip.npz (t, shot, emb).
Photos (.jpg .jpeg .png .webp .heic? no): one embedding of the EXIF-corrected image.
Search with tools/search_footage.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import assets  # noqa: E402

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mts"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
EMBED_W = 384


def index_video(path: Path, every: float, fresh: bool) -> Path:
    import analyze_video as av
    import siglip
    out = assets.analysis_dir(path) / "siglip.npz"
    if out.exists() and not fresh:
        return out
    res = av.analyze(path, quiet=True)
    shots = res["shots"]
    starts = np.array([s["start"] for s in shots])
    ts, ims = [], []
    for t, rgb in av.frames(path, EMBED_W, 1.0 / every, res["meta"]):
        ts.append(t + 0.5 * every)  # fps filter picks the frame near the middle of each interval
        ims.append(rgb)
    for s in shots:  # make sure every shot (even a short one) has its best frame indexed
        ts.append(s["best_t"])
        ims.append(av.grab(path, s["best_t"], EMBED_W))
    emb = siglip.embed_images(ims)
    shot_of = np.searchsorted(starts, np.array(ts), side="right") - 1
    np.savez_compressed(out, t=np.array(ts, np.float32), shot=shot_of.astype(np.int32), emb=emb,
                        model=siglip.MODEL, kind="video")
    return out


def index_photo(path: Path, fresh: bool) -> Path:
    from PIL import Image, ImageOps
    import siglip
    out = assets.analysis_dir(path) / "siglip.npz"
    if out.exists() and not fresh:
        return out
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((EMBED_W * 2, EMBED_W * 2))
        emb = siglip.embed_images([im])
    np.savez_compressed(out, t=np.zeros(1, np.float32), shot=np.zeros(1, np.int32), emb=emb,
                        model=siglip.MODEL, kind="photo")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--every", type=float, default=1.0, help="seconds between indexed video frames")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    files: list[Path] = []
    for p in a.paths:
        files += sorted(f for f in p.rglob("*") if f.suffix.lower() in VIDEO_EXT | PHOTO_EXT) if p.is_dir() else [p]
    for f in files:
        t0 = time.time()
        kind = "video" if f.suffix.lower() in VIDEO_EXT else "photo"
        out = index_video(f, a.every, a.fresh) if kind == "video" else index_photo(f, a.fresh)
        n = len(np.load(out)["t"])
        print(f"{kind:5} {f.name}: {n} embedding(s) in {time.time() - t0:.1f} s -> {out.parent.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

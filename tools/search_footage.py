"""Search indexed footage and photos by text, e.g. "crowd with placards", "close-up of a cow".

Usage:  uv run tools/search_footage.py "query" [--top 10] [--assets id1,id2] [--sheet] [--json]

Ranks shots (videos) and photos across every analysis/<id>/siglip.npz (tools/index_footage.py),
by the best-matching frame in each shot. --sheet writes _previews/search.jpg (thumbnails with
rank, asset, time range and score) for Claude to look at. Scores are SigLIP's calibrated match
probability: compare within one query, not across queries.
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


def load_index(only: set[str] | None = None) -> list[dict]:
    items = []
    for f in sorted((cfg.ROOT / "analysis").glob("*/siglip.npz")):
        aid = f.parent.name
        if only and aid not in only:
            continue
        z = np.load(f)
        items.append({"asset_id": aid, "kind": str(z["kind"]), "t": z["t"], "shot": z["shot"], "emb": z["emb"]})
    return items


def search(query: str, top: int = 10, only: set[str] | None = None) -> list[dict]:
    import siglip
    q = siglip.embed_text([query])[0].astype(np.float32)
    results = []
    for it in load_index(only):
        sims = it["emb"].astype(np.float32) @ q
        if it["kind"] == "photo":
            results.append({"asset_id": it["asset_id"], "kind": "photo", "sim": float(sims.max()), "t": 0.0})
            continue
        vj = json.loads((cfg.ROOT / "analysis" / it["asset_id"] / "video.json").read_text(encoding="utf-8"))
        for shot in np.unique(it["shot"]):
            m = it["shot"] == shot
            k = int(np.argmax(np.where(m, sims, -9)))
            s = vj["shots"][int(shot)]
            results.append({"asset_id": it["asset_id"], "kind": "video", "shot": int(shot), "sim": float(sims[k]),
                            "t": round(float(it["t"][k]), 2), "start": s["start"], "end": s["end"],
                            "source": vj["source"]})
    results.sort(key=lambda r: -r["sim"])
    results = results[:top]
    if results:
        probs = siglip.logit(np.array([r["sim"] for r in results]))
        for r, p in zip(results, probs):
            r["score"] = round(float(p), 4)
            r["sim"] = round(r["sim"], 4)
    return results


def sheet(results: list[dict], query: str) -> Path:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    import analyze_video as av
    tw, cols = 320, 5
    tiles = []
    for r in results:
        if r["kind"] == "video":
            img = Image.fromarray(av.grab(Path(r["source"]), r["t"], tw))
        else:
            src = json.loads((cfg.ROOT / "analysis" / r["asset_id"] / "asset.json").read_text(encoding="utf-8"))["source"]
            img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
            img.thumbnail((tw, tw))
        tiles.append(img)
    th = max((t.height for t in tiles), default=180)
    rows = (len(tiles) + cols - 1) // cols
    out = Image.new("RGB", (cols * tw, 30 + rows * (th + 36)), (16, 16, 18))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.truetype(str(cfg.path("fonts") / "inter" / "Inter[opsz,wght].ttf"), 14)
    except OSError:
        font = ImageFont.load_default()
    d.text((8, 6), f"query: {query}", fill=(255, 184, 48), font=font)
    for i, (r, img) in enumerate(zip(results, tiles)):
        x, y = (i % cols) * tw, 30 + (i // cols) * (th + 36)
        out.paste(img, (x, y))
        where = f"shot {r['shot']} {r['start']:.1f}-{r['end']:.1f}s" if r["kind"] == "video" else "photo"
        d.text((x + 4, y + th + 2), f"#{i + 1} {r['asset_id'][:22]}", fill=(240, 236, 228), font=font)
        d.text((x + 4, y + th + 18), f"{where}  p={r['score']:.3f}", fill=(180, 180, 180), font=font)
    p = cfg.ROOT / "_previews" / "search.jpg"
    p.parent.mkdir(exist_ok=True)
    out.save(p, quality=85)
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--assets", help="comma-separated asset ids to search (default: all)")
    ap.add_argument("--sheet", action="store_true", help="write _previews/search.jpg")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = search(a.query, a.top, set(a.assets.split(",")) if a.assets else None)
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
    else:
        for i, r in enumerate(res, 1):
            where = f"shot {r['shot']:>3} {r['start']:7.2f}-{r['end']:7.2f}s (best {r['t']:.1f}s)" \
                if r["kind"] == "video" else "photo"
            print(f"{i:>2}. p={r['score']:.4f} sim={r['sim']:.3f}  {r['asset_id']}  {where}")
    if a.sheet:
        print(f"sheet: {sheet(res, a.query)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

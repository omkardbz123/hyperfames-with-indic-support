"""Analyse photos for slideshows and promos: orientation, quality, duplicates, faces, focus.

Usage:  uv run tools/analyze_photos.py <folder|files...> [--sheet out.jpg] [--fresh]

Per photo -> analysis/<asset-id>/photo.json:
- EXIF orientation applied (ImageOps.exif_transpose, always), display size, megapixels,
  EXIF date/camera when present
- blur: variance of Laplacian at 1024 px long side (`sharpness`); `blurry` below 60
- exposure: mean luma, % clipped highlights / crushed shadows
- faces (YuNet) and a Ken Burns `focus` point (largest face, else saliency centre)
- crop fit: the largest 9:16 and 16:9 crops in source pixels; `needs_upscale_916` when a
  9:16 crop is under 1920 px tall (Goa lesson: soft vertical crops of landscape photos)
For the set: near-duplicate groups (perceptual hash, Hamming <= 8) with the best one marked
(`keep`), and an optional contact sheet with flags for Claude to look at.
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

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
BLURRY = 60.0
DUP_DIST = 8


def load(path: Path):
    from PIL import Image, ImageOps
    im = Image.open(path)
    exif = im.getexif()
    orient = int(exif.get(0x0112, 1))
    disp = ImageOps.exif_transpose(im).convert("RGB")
    return disp, exif, orient


def analyse_one(path: Path, fresh: bool = False) -> dict:
    import cv2
    import imagehash
    import analyze_video as av
    out_p = assets.analysis_dir(path) / "photo.json"
    if out_p.exists() and not fresh:
        return json.loads(out_p.read_text(encoding="utf-8"))
    img, exif, orient = load(path)
    w, h = img.size
    small = img.copy()
    small.thumbnail((1024, 1024))
    rgb = np.asarray(small)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    faces = av.detect_faces(av.face_detector(), rgb)
    if faces:
        f = max(faces, key=lambda f: f["w"] * f["h"])
        focus, focus_by = [f["x"], f["y"]], "face"
    else:
        sal = cv2.saliency.StaticSaliencySpectralResidual_create()
        ok, m = sal.computeSaliency(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
        if ok and m.sum() > 0:
            ys, xs = np.indices(m.shape)
            focus = [float((m * xs).sum() / m.sum() / m.shape[1]), float((m * ys).sum() / m.sum() / m.shape[0])]
        else:
            focus = [0.5, 0.5]
        focus_by = "saliency"
    crop916 = [min(w, int(h * 9 / 16)), min(h, int(w * 16 / 9))]
    crop169 = [min(w, int(h * 16 / 9)), min(h, int(w * 9 / 16))]
    res = {
        "asset_id": out_p.parent.name, "source": str(path.resolve()), "w": w, "h": h,
        "megapixels": round(w * h / 1e6, 2), "exif_orientation": orient, "rotated": orient not in (1, 0),
        "taken": exif.get(0x0132) or exif.get_ifd(0x8769).get(0x9003) if exif else None,
        "camera": " ".join(str(exif.get(k, "")) for k in (0x010F, 0x0110)).strip() or None,
        "sharpness": round(sharp, 1), "blurry": sharp < BLURRY,
        "brightness": round(float(gray.mean() / 255), 3),
        "clipped_highlights": round(float((gray >= 250).mean()), 4),
        "crushed_shadows": round(float((gray <= 5).mean()), 4),
        "faces": faces, "focus": [round(v, 3) for v in focus], "focus_by": focus_by,
        "crop_916": crop916, "needs_upscale_916": crop916[1] < 1920,
        "crop_169": crop169, "needs_upscale_169": crop169[0] < 1920,
        "phash": str(imagehash.phash(small)), "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out_p.write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return res


def duplicate_groups(items: list[dict]) -> list[list[int]]:
    import imagehash
    hs = [imagehash.hex_to_hash(it["phash"]) for it in items]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if hs[i] - hs[j] <= DUP_DIST:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(len(items)):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) > 1]


def analyse_set(paths: list[Path], fresh: bool = False) -> list[dict]:
    items = [analyse_one(p, fresh) for p in paths]
    for it in items:
        it["duplicate_of"], it["keep"] = None, True
    for g in duplicate_groups(items):
        # keep: not blurry, largest, then (within 10 % sharpness) no EXIF rotation, then earliest name
        ok = [i for i in g if not items[i]["blurry"]] or g
        mp = max(items[i]["megapixels"] for i in ok)
        ok = [i for i in ok if items[i]["megapixels"] >= 0.95 * mp]
        sh = max(items[i]["sharpness"] for i in ok)
        ok = [i for i in ok if items[i]["sharpness"] >= 0.9 * sh]
        best = min(ok, key=lambda i: (items[i]["rotated"], Path(items[i]["source"]).name))
        for i in g:
            if i != best:
                items[i]["duplicate_of"], items[i]["keep"] = items[best]["asset_id"], False
    return items


def sheet(items: list[dict], out: Path, cols: int = 5) -> Path:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    tw = 300
    tiles = []
    for it in items:
        im = ImageOps.exif_transpose(Image.open(it["source"])).convert("RGB")
        im.thumbnail((tw, tw))
        d = ImageDraw.Draw(im)
        fx, fy = it["focus"][0] * im.width, it["focus"][1] * im.height
        d.ellipse([fx - 6, fy - 6, fx + 6, fy + 6], outline=(255, 184, 48), width=3)
        for f in it["faces"]:
            d.rectangle([(f["x"] - f["w"] / 2) * im.width, (f["y"] - f["h"] / 2) * im.height,
                         (f["x"] + f["w"] / 2) * im.width, (f["y"] + f["h"] / 2) * im.height], outline=(0, 255, 0), width=2)
        tiles.append(im)
    rows = (len(tiles) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * tw, rows * (tw + 40)), (16, 16, 18))
    dr = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(str(cfg.path("fonts") / "inter" / "Inter[opsz,wght].ttf"), 13)
    except OSError:
        font = ImageFont.load_default()
    for i, (it, im) in enumerate(zip(items, tiles)):
        x, y = (i % cols) * tw, (i // cols) * (tw + 40)
        canvas.paste(im, (x + (tw - im.width) // 2, y + (tw - im.height) // 2))
        flags = [k for k, v in (("BLURRY", it["blurry"]), ("DUP", not it["keep"]), ("ROT", it["rotated"]),
                                ("UPSCALE 9:16", it["needs_upscale_916"])) if v]
        dr.text((x + 4, y + tw + 2), f"{Path(it['source']).name[:34]}", fill=(240, 236, 228), font=font)
        dr.text((x + 4, y + tw + 19), f"{it['w']}x{it['h']} sharp {it['sharpness']:.0f} {' '.join(flags)}",
                fill=(255, 120, 120) if flags else (170, 170, 170), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=85)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--sheet", type=Path, help="write a flagged contact sheet here")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    files: list[Path] = []
    for p in a.paths:
        files += sorted(f for f in p.rglob("*") if f.suffix.lower() in PHOTO_EXT) if p.is_dir() else [p]
    items = analyse_set(files, a.fresh)
    for it in items:
        flags = [k for k, v in (("blurry", it["blurry"]), (f"dup of {it['duplicate_of']}", not it["keep"]),
                                (f"exif-rot {it['exif_orientation']}", it["rotated"]),
                                ("9:16 needs upscale", it["needs_upscale_916"])) if v]
        print(f"{Path(it['source']).name:<28} {it['w']}x{it['h']}  sharp {it['sharpness']:7.1f}  "
              f"faces {len(it['faces'])}  focus {it['focus']} ({it['focus_by']})  {', '.join(flags)}")
    if a.sheet:
        print(f"sheet: {sheet(items, a.sheet)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

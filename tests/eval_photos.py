"""Score tools/analyze_photos.py on generated photos with exact truth.

Usage:  uv run tests/eval_photos.py

Builds tests/fixtures/photos/ from Tears of Steel excerpt frames (CC BY 3.0):
  p01..p06  distinct frames (p05/p06 contain faces)
  p07_rot   = p02 stored sideways with EXIF Orientation 6 (must come out landscape)
  p08_small = p03 at half size, re-compressed (duplicate of p03; p03 kept)
  p09_blur  = p04 with Gaussian blur sigma 4 (blurry; duplicate of p04; p04 kept)
Checks orientation, blur flags, duplicate groups + which one is kept, faces and focus.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import analyze_photos as ap  # noqa: E402
import analyze_video as av  # noqa: E402

SRC = ROOT / "tests" / "fixtures" / "footage" / "tos_60-180.mp4"
OUT = ROOT / "tests" / "fixtures" / "photos"
FRAMES = {"p01": 12.0, "p02": 16.0, "p03": 28.0, "p04": 47.0, "p05": 81.5, "p06": 116.0}


def build() -> None:
    from PIL import Image, ImageFilter
    OUT.mkdir(parents=True, exist_ok=True)
    for name, t in FRAMES.items():
        Image.fromarray(av.grab(SRC, t, 1920)).save(OUT / f"{name}.jpg", quality=92)
    p02 = Image.open(OUT / "p02.jpg")
    ex = Image.Exif()
    ex[0x0112] = 6  # display = rotate 90° clockwise
    p02.transpose(Image.Transpose.ROTATE_90).save(OUT / "p07_rot.jpg", quality=92, exif=ex.tobytes())
    p03 = Image.open(OUT / "p03.jpg")
    p03.resize((p03.width // 2, p03.height // 2)).save(OUT / "p08_small.jpg", quality=70)
    Image.open(OUT / "p04.jpg").filter(ImageFilter.GaussianBlur(4)).save(OUT / "p09_blur.jpg", quality=92)


def main() -> int:
    if not (OUT / "p09_blur.jpg").exists():
        build()
    files = sorted(OUT.glob("*.jpg"))
    items = {Path(i["source"]).stem: i for i in ap.analyse_set(files, fresh=True)}
    checks = []

    def check(name, cond, detail=""):
        checks.append(bool(cond))
        print(f"{'PASS' if cond else 'FAIL'}  {name:<44} {detail}")

    r = items["p07_rot"]
    check("EXIF-rotated photo displays landscape", r["w"] > r["h"] and r["rotated"], f"{r['w']}x{r['h']}, orient {r['exif_orientation']}")
    blurry = sorted(k for k, v in items.items() if v["blurry"])
    check("only the blurred copy is flagged blurry", blurry == ["p09_blur"], f"{blurry}  sharpness: " +
          ", ".join(f"{k} {v['sharpness']:.0f}" for k, v in sorted(items.items())))
    dups = {k: v["duplicate_of"] for k, v in items.items() if v["duplicate_of"]}
    want = {"p08_small": items["p03"]["asset_id"], "p09_blur": items["p04"]["asset_id"],
            "p07_rot": items["p02"]["asset_id"]}
    check("duplicates found and the originals kept", dups == want, json.dumps({k: v[:8] for k, v in dups.items()}))
    faces = {k: len(v["faces"]) for k, v in items.items()}
    check("faces found in p05 and p06", faces["p05"] >= 1 and faces["p06"] >= 1, str(faces))
    check("focus on a face when there is one", all(items[k]["focus_by"] == "face" for k in ("p05", "p06")))
    check("1920x800 frames need upscaling for 9:16", items["p01"]["needs_upscale_916"], str(items["p01"]["crop_916"]))
    print(f"sheet: {ap.sheet(list(items.values()), ROOT / '_previews' / 'photos_sheet.jpg')}")
    ok = all(checks)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

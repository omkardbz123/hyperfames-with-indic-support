"""Generate the studio's own colour looks as 33-point .cube LUTs into library/luts/.

Usage:  uv run tools/make_luts.py [--size 33] [--preview frame.png]

Looks (made here, so no licence to track): bw_contrast (phonk/B&W high contrast), teal_orange,
warm_film, cool_night, faded_matte. Apply with tools/fx.py lut, ffmpeg lut3d, or HyperFrames
media treatments. --preview writes _previews/luts.jpg with every look on one frame.
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

LUMA = np.array([0.2126, 0.7152, 0.0722])


def s_curve(x, strength):
    """Contrast S-curve around mid-grey (0..1 -> 0..1)."""
    return 0.5 + np.tanh((x - 0.5) * strength) / (2 * np.tanh(0.5 * strength))


def bw_contrast(rgb):
    y = rgb @ LUMA
    y = s_curve(np.clip((y - 0.04) / 0.92, 0, 1), 4.2)
    return np.repeat(y[..., None], 3, -1)


def teal_orange(rgb):
    y = (rgb @ LUMA)[..., None]
    sat = y + (rgb - y) * 1.15
    shadow = np.array([-0.04, 0.03, 0.07]) * (1 - y) ** 2       # teal into shadows
    high = np.array([0.08, 0.03, -0.06]) * y ** 2               # orange into highlights / skin
    out = sat + shadow + high
    return s_curve(np.clip(out, 0, 1), 1.6)


def warm_film(rgb):
    y = (rgb @ LUMA)[..., None]
    out = y + (rgb - y) * 0.9
    out = out * np.array([1.05, 1.0, 0.9]) + np.array([0.03, 0.02, 0.0])
    out = 0.04 + 0.92 * s_curve(np.clip(out, 0, 1), 1.8)      # lifted blacks, soft whites
    return out


def cool_night(rgb):
    y = (rgb @ LUMA)[..., None]
    out = y + (rgb - y) * 0.7
    out = out * np.array([0.88, 0.97, 1.12])
    return s_curve(np.clip(out * 0.92, 0, 1), 2.2)


def faded_matte(rgb):
    y = (rgb @ LUMA)[..., None]
    out = y + (rgb - y) * 0.8
    return 0.08 + 0.84 * np.clip(out, 0, 1)


LOOKS = {"bw_contrast": bw_contrast, "teal_orange": teal_orange, "warm_film": warm_film,
         "cool_night": cool_night, "faded_matte": faded_matte}


def write_cube(path: Path, fn, size: int) -> None:
    g = np.linspace(0, 1, size)
    # .cube order: red changes fastest, then green, then blue
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")
    rgb = np.stack([r, gg, b], -1).reshape(-1, 3)
    out = np.clip(fn(rgb), 0, 1)
    lines = [f'TITLE "{path.stem} (ai-video-studio)"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    lines += [f"{a:.6f} {b_:.6f} {c:.6f}" for a, b_, c in out]
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=int, default=33)
    ap.add_argument("--preview", type=Path)
    a = ap.parse_args()
    d = cfg.ROOT / "library" / "luts"
    d.mkdir(parents=True, exist_ok=True)
    index = []
    for name, fn in LOOKS.items():
        p = d / f"{name}.cube"
        write_cube(p, fn, a.size)
        index.append({"name": name, "file": p.name, "license": "own work (ai-video-studio)", "size": a.size})
        print(f"wrote {p}")
    (d / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    if a.preview:
        from PIL import Image
        src = np.asarray(Image.open(a.preview).convert("RGB").resize((480, 200))) / 255.0
        tiles = [src] + [np.clip(fn(src.reshape(-1, 3)).reshape(src.shape), 0, 1) for fn in LOOKS.values()]
        Image.fromarray((np.vstack(tiles) * 255).astype(np.uint8)).save(cfg.ROOT / "_previews" / "luts.jpg", quality=88)
        print("preview: _previews/luts.jpg (original, then " + ", ".join(LOOKS) + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())

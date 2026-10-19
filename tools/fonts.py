"""Ship library fonts into a HyperFrames project and write their @font-face rules.

Usage:  uv run tools/fonts.py list
        uv run tools/fonts.py ship projects/<slug> "Mukta" --weight 800

As a library: face(project, family, weight=400, italic=False) copies the best file from
library/fonts/<dir>/ to <project>/assets/fonts/ and returns the @font-face CSS (variable fonts
cover every weight). is_devanagari(text) tells whether a string needs a Devanagari font.
Remember: Yatra One shows broken conjuncts (क्‌ष); use it only for words without conjuncts.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

WEIGHTS = {"Thin": 100, "ExtraLight": 200, "Light": 300, "Regular": 400, "Medium": 500, "SemiBold": 600,
           "Bold": 700, "ExtraBold": 800, "Black": 900}
DEVA = re.compile(r"[ऀ-ॿ]")


def is_devanagari(text: str) -> bool:
    return bool(DEVA.search(text or ""))


def index() -> dict[str, dict]:
    rows = json.loads((cfg.path("fonts") / "index.json").read_text(encoding="utf-8"))
    return {r["family"]: r for r in rows}


def pick(family: str, weight: int = 400, italic: bool = False) -> tuple[Path, str]:
    """-> (font file, css font-weight value)."""
    fam = family.replace(" Italic", "")
    italic = italic or family.endswith(" Italic")
    row = index().get(fam)
    if row is None:
        raise SystemExit(f"font {family!r} not in library/fonts/index.json")
    d = cfg.path("fonts") / row["dir"]
    files = [f for f in row["files"] if ("Italic" in f) == italic] or row["files"]
    var = [f for f in files if "[" in f]
    if var:
        return d / var[0], "100 900"
    best = min(files, key=lambda f: abs(WEIGHTS.get(f.split("-")[-1].split(".")[0].replace("Italic", "") or "Regular", 400) - weight))
    w = WEIGHTS.get(best.split("-")[-1].split(".")[0].replace("Italic", "") or "Regular", 400)
    return d / best, str(w)


def face(project: Path, family: str, weight: int = 400, italic: bool = False) -> str:
    src, w = pick(family, weight, italic)
    safe = re.sub(r"[\[\],]", "_", src.name)
    dst = Path(project) / "assets" / "fonts" / safe
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy(src, dst)
    css_family = family.replace(" Italic", "")
    style = "italic" if (italic or family.endswith(" Italic")) else "normal"
    return (f'@font-face {{ font-family: "{css_family}"; src: url("assets/fonts/{safe}") format("truetype"); '
            f'font-weight: {w}; font-style: {style}; }}')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    s = sub.add_parser("ship")
    s.add_argument("project", type=Path)
    s.add_argument("family")
    s.add_argument("--weight", type=int, default=400)
    s.add_argument("--italic", action="store_true")
    a = ap.parse_args()
    if a.cmd == "list":
        for fam, r in sorted(index().items()):
            print(f"{fam:<28} {'Devanagari' if r.get('devanagari') else 'Latin':<11} {', '.join(r['files'])}")
    else:
        print(face(a.project, a.family, a.weight, a.italic))
    return 0


if __name__ == "__main__":
    sys.exit(main())

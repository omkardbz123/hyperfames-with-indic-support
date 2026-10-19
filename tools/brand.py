"""Brand kits: colours, fonts, handle, event facts and end-card lines per brand.

Usage:  uv run tools/brand.py show <brand>          (e.g. goaalm)
        uv run tools/brand.py check <brand>         (fonts exist, colours valid, open questions)
        uv run tools/brand.py new <brand> --name "..." [--handle @x] [--accent #RRGGBB]

Kits live in library/brands/<brand>/brand.json (+ logo files beside it). tools/build.py reads
`colors`, `fonts`, `caption`, `grades`, `end_card` (lines may use {name}, {handle},
{event.date} ...) and refuses to export while `to_confirm` lists event facts, unless forced.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

BRANDS = cfg.ROOT / "library" / "brands"
FONT_DIRS = {"Anton": "anton", "Montserrat": "montserrat", "Playfair Display Italic": "playfairdisplay",
             "Playfair Display": "playfairdisplay", "Mukta": "mukta", "Hind": "hind", "Baloo 2": "baloo2",
             "Noto Sans Devanagari": "notosansdevanagari", "Inter": "inter", "Poppins": "poppins",
             "Bebas Neue": "bebasneue", "Oswald": "oswald", "Kalam": "kalam", "Rozha One": "rozhaone"}


def load(brand: str) -> dict:
    p = BRANDS / brand / "brand.json"
    if not p.exists():
        raise SystemExit(f"no brand kit {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def fill(template: str, b: dict) -> str:
    def get(path):
        cur = b
        for k in path.split("."):
            cur = cur.get(k, "") if isinstance(cur, dict) else ""
        return str(cur)
    return re.sub(r"\{([a-z_.]+)\}", lambda m: get(m.group(1)), template)


def check(b: dict) -> list[str]:
    issues = []
    for role, fam in b.get("fonts", {}).items():
        d = FONT_DIRS.get(fam)
        if not d or not (cfg.path("fonts") / d).exists():
            issues.append(f"font {fam} ({role}) not in library/fonts")
    for k, v in b.get("colors", {}).items():
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", v):
            issues.append(f"colour {k}={v} is not #RRGGBB")
    if b.get("logo") and not (BRANDS / b["id"] / b["logo"]).exists():
        issues.append(f"logo {b['logo']} missing")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("show", "check"):
        sub.add_parser(c).add_argument("brand")
    n = sub.add_parser("new")
    n.add_argument("brand")
    n.add_argument("--name", required=True)
    n.add_argument("--handle", default="")
    n.add_argument("--accent", default="#FFB830")
    a = ap.parse_args()
    if a.cmd == "new":
        d = BRANDS / a.brand
        d.mkdir(parents=True, exist_ok=True)
        kit = {"id": a.brand, "name": a.name, "handle": a.handle, "tagline": "",
               "colors": {"accent": a.accent, "paper": "#F4F0E8", "ink": "#0C0C0E"},
               "fonts": {"display": "Anton", "body": "Montserrat", "devanagari_display": "Mukta", "devanagari_body": "Hind"},
               "caption": {"style": "kinetic", "font": "Mukta", "fg": "#F4F0E8", "accent": a.accent},
               "grades": {"default": "warm_film"}, "logo": None, "event": {},
               "end_card": {"lines": ["{name}", "{handle}"]}, "to_confirm": ["everything: new kit"]}
        (d / "brand.json").write_text(json.dumps(kit, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {d / 'brand.json'}")
        return 0
    b = load(a.brand)
    if a.cmd == "show":
        print(json.dumps(b, indent=2, ensure_ascii=False))
        print("end card:", " | ".join(fill(l, b) for l in b.get("end_card", {}).get("lines", [])))
    else:
        issues = check(b)
        print("OK" if not issues else "\n".join(issues))
        if b.get("to_confirm"):
            print("to confirm with the user:", "; ".join(b["to_confirm"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())

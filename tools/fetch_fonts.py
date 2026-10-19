"""Download OFL fonts from the official google/fonts GitHub repo into library/fonts/.

Usage:  uv run tools/fetch_fonts.py [family-dir ...]     (default: the studio set)
        uv run tools/fetch_fonts.py --list

Each family lands in library/fonts/<family-dir>/ with its OFL.txt; library/fonts/index.json
records family, files, licence and source for credits.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

API = "https://api.github.com/repos/google/fonts/contents/ofl/{}"
RAW = "https://raw.githubusercontent.com/google/fonts/main/ofl/{}/{}"

DEVANAGARI = ["notosansdevanagari", "notoserifdevanagari", "mukta", "hind",
              "tirodevanagarimarathi", "tirodevanagarihindi", "baloo2", "kalam",
              "yatraone", "rozhaone"]
LATIN = ["anton", "bebasneue", "montserrat", "inter", "oswald", "playfairdisplay", "poppins"]
DEFAULT = DEVANAGARI + LATIN


def get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ai-video-studio-font-fetch"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def family_name(meta: str, fallback: str) -> str:
    for line in meta.splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip('"')
    return fallback


def fetch(fam: str, dest_root: Path) -> dict:
    listing = json.loads(get(API.format(fam)))
    want = [f["name"] for f in listing
            if f["type"] == "file" and f["name"].lower().endswith((".ttf", ".otf"))
            or f["name"] in ("OFL.txt", "METADATA.pb")]
    dest = dest_root / fam
    dest.mkdir(parents=True, exist_ok=True)
    for name in want:
        p = dest / name
        if not p.exists():
            p.write_bytes(get(RAW.format(fam, urllib.request.quote(name))))
            time.sleep(0.3)
    meta = (dest / "METADATA.pb").read_text(encoding="utf-8") if (dest / "METADATA.pb").exists() else ""
    return {
        "dir": fam,
        "family": family_name(meta, fam),
        "files": sorted(n for n in want if n.lower().endswith((".ttf", ".otf"))),
        "license": "OFL-1.1",
        "source": f"https://github.com/google/fonts/tree/main/ofl/{fam}",
        "devanagari": fam in DEVANAGARI,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("families", nargs="*", help="google/fonts ofl/ directory names")
    ap.add_argument("--list", action="store_true", help="print the default set and exit")
    a = ap.parse_args()
    if a.list:
        print("\n".join(DEFAULT))
        return 0
    root = cfg.path("fonts")
    idx_path = root / "index.json"
    index = {e["dir"]: e for e in json.loads(idx_path.read_text(encoding="utf-8"))} if idx_path.exists() else {}
    failed = []
    for fam in a.families or DEFAULT:
        try:
            e = fetch(fam, root)
            index[fam] = e
            print(f"ok   {e['family']:<28} {len(e['files'])} file(s)")
        except Exception as ex:  # noqa: BLE001
            failed.append(fam)
            print(f"FAIL {fam}: {ex}")
    idx_path.write_text(json.dumps(sorted(index.values(), key=lambda e: e["dir"]), indent=2,
                                   ensure_ascii=False), encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

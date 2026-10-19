"""Score footage search relevance on the Tears of Steel excerpt.

Usage:  uv run tests/eval_search.py

Expected shots were identified by eye from the excerpt's contact sheet (2026-10-19).
hit@1 / hit@3 = an expected shot is the first / among the first three results.
Pass: hit@3 = 100 % and hit@1 >= 80 %.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import assets  # noqa: E402
import index_footage  # noqa: E402
import search_footage  # noqa: E402

SRC = ROOT / "tests" / "fixtures" / "footage" / "tos_60-180.mp4"
QUERIES = {
    "a man aiming a sniper rifle": {5, 7, 11, 14, 16},
    "aerial view of an old city with church towers": {2},
    "an old man with grey hair": {12, 13, 15, 18, 19},
    "a newspaper": {4, 9},
    "a man and a woman standing in a room with lamps": {19},
    "a flying ship seen through a rifle scope": {6, 8, 10},
    "a human brain": {0},
    "movie title text on a black background": {1},
    "a huge church organ in a gothic hall": {17},
}


def main() -> int:
    index_footage.index_video(SRC, 1.0, False)
    aid = assets.asset_id(SRC)
    h1 = h3 = 0
    t0 = time.time()
    for q, want in QUERIES.items():
        res = search_footage.search(q, top=3, only={aid})
        got = [r["shot"] for r in res]
        a1, a3 = got[0] in want, bool(set(got) & want)
        h1 += a1
        h3 += a3
        print(f"{'ok ' if a3 else 'MISS'} {q:<52} top3 {got}  expected {sorted(want)}")
    n = len(QUERIES)
    ok = h3 == n and h1 >= 0.8 * n
    print(f"hit@1 {h1}/{n}  hit@3 {h3}/{n}  ({(time.time() - t0) / n:.2f} s per query incl. model load)")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Phase 10 acceptance: a deliberately broken render must be caught by tools/review.py.

Usage:  uv run tests/make_broken_render.py [--src projects/_test-qa] [--render]

Copies a built project (default projects/_test-qa, built with tools/build.py) to
projects/_test-qa-broken and sabotages the page and the mix WITHOUT touching build.json (which
still describes the intended video), then renders and runs the review. Breakages:
  1. late cut     clip c03 starts 4 frames (0.133 s) after its downbeat
  2. captions     caption page 1 is held 0.6 s into page 2 (two pages on screen at once)
  3. audio        the mix is boosted +12 dB with no limiter (clipping)
  4. text         the title is enlarged to 300 px (runs out of the safe zone)
Pass = review exits 1 and flags cut_sync, captions, loudness and safe_zone.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=ROOT / "projects" / "_test-qa")
    a = ap.parse_args()
    dst = ROOT / "projects" / "_test-qa-broken"
    if dst.exists():
        trash = ROOT / "_trash" / f"{dst.name}_prev"
        if trash.exists():
            shutil.rmtree(trash)  # our own previous throwaway copy inside _trash
        shutil.move(str(dst), str(trash))
    shutil.copytree(a.src, dst, ignore=shutil.ignore_patterns("renders", "review", ".hyperframes"))
    bj = json.loads((dst / "build.json").read_text(encoding="utf-8"))
    idx = (dst / "index.html").read_text(encoding="utf-8")
    # 1. late cut: c03 (scene index 2) starts 4 frames late, c02 holds 4 frames longer
    shift = 4 / bj["format"]["fps"]
    c02 = re.search(r'<video id="v1"[^>]*data-start="([\d.]+)" data-duration="([\d.]+)"', idx)
    c03 = re.search(r'<video id="v2"[^>]*data-start="([\d.]+)" data-duration="([\d.]+)"', idx)
    idx = idx.replace(c02.group(0), c02.group(0).replace(f'data-duration="{c02.group(2)}"',
                                                         f'data-duration="{float(c02.group(2)) + shift:.4f}"'))
    idx = idx.replace(c03.group(0), c03.group(0).replace(f'data-start="{c03.group(1)}"',
                                                         f'data-start="{float(c03.group(1)) + shift:.4f}"'))
    # 4. oversized title
    idx = re.sub(r'(<div id="tx0".*?font-size: )\d+px', r"\g<1>300px", idx, count=1, flags=re.S)
    (dst / "index.html").write_text(idx, encoding="utf-8")
    # 2. overlapping caption pages
    cap = dst / "compositions" / "captions.html"
    s = cap.read_text(encoding="utf-8")
    C = json.loads(re.search(r"var C = (\[.*?\]);\n", s, re.S).group(1))
    C[0]["e"] = round(C[1]["s"] + 0.6, 3)
    s = re.sub(r"var C = \[.*?\];\n", lambda m: f"var C = {json.dumps(C)};\n", s, count=1, flags=re.S)
    cap.write_text(s, encoding="utf-8")
    # 3. clipping audio
    mix = dst / "assets" / "audio" / "mix.wav"
    hot = mix.with_name("mix_hot.wav")
    subprocess.run([cfg.ffmpeg(), "-v", "error", "-y", "-i", str(mix), "-af", "volume=12dB", "-c:a", "pcm_s16le", str(hot)], check=True)
    shutil.move(str(hot), str(mix))
    print("sabotaged: late cut c03 (+4 frames), caption pages overlap 0.6 s, mix +12 dB, title 300 px")
    import hf
    r = hf.run(["render", "-o", "renders/draft.mp4", "--quiet"], cwd=dst)
    if r.returncode:
        return 2
    rev = subprocess.run([sys.executable, str(ROOT / "tools" / "review.py"), str(dst), "--no-hf-check"],
                         capture_output=True, text=True, encoding="utf-8")
    print(rev.stdout[-3000:])
    res = json.loads((dst / "review" / "review.json").read_text(encoding="utf-8"))
    failed = {c["name"] for c in res["checks"] if c["status"] == "fail"}
    want = {"cut_sync", "captions", "loudness", "safe_zone"}
    print(f"\nexpected failures {sorted(want)}; review flagged {sorted(failed)}")
    ok = want <= failed and rev.returncode == 1
    print("ACCEPTANCE: PASS (every breakage caught)" if ok else f"ACCEPTANCE: FAIL (missed {sorted(want - failed)})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

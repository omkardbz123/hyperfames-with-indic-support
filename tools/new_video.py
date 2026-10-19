"""Start a new video: projects/<slug>/ with brief.md, plan.md and the HyperFrames project files.

Usage:  uv run tools/new_video.py <slug> [--recipe beat-sync] [--format reels] [--brand goaalm]
                                  [--lang mr] [--title "..."]

Never overwrites: an existing project is left alone (it prints what is there). Writes:
  brief.md   the request template (BUILD_PLAN §15.2) prefilled from the arguments + recipe defaults
  plan.md    the plan skeleton /plan fills in (concept, structure + timings, music, shots, text in
             every language, VO script, transitions/effects, aspect ratios, open questions)
  hyperframes.json / meta.json / package.json, and media/ for files that belong to this video
edl.json is written by /plan once the brief is clear (schema: docs/CONTRACTS.md).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

RECIPES = {
    "beat-sync": ("Beat-sync montage", "reels", "15-20 s", "bw_contrast"),
    "promo": ("Promo / event invite", "reels", "30 s", "warm_film"),
    "talking-head": ("Talking head reel", "reels", "30-60 s", "none"),
    "lyric": ("Lyric video", "reels", "song length", "faded_matte"),
    "slideshow": ("Photo slideshow", "reels", "60 s", "warm_film"),
    "explainer": ("Explainer", "reels", "45 s", "none"),
    "trailer": ("Trailer / teaser", "youtube", "30 s", "teal_orange"),
    "tutorial": ("Tutorial", "youtube", "2-5 min", "none"),
    "subtitles-dub": ("Subtitles / dub", "source", "source", "none"),
    "recap": ("Event recap", "youtube", "2-4 min", "warm_film"),
    "restoration": ("Restoration", "source", "source", "none"),
    "meme": ("Meme / template", "reels", "10-20 s", "none"),
    "repurpose": ("Multi-format repurpose", "reels", "source", "none"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--recipe", default="promo", choices=sorted(RECIPES))
    ap.add_argument("--format")
    ap.add_argument("--brand")
    ap.add_argument("--lang", default="mr")
    ap.add_argument("--title")
    a = ap.parse_args()
    slug = re.sub(r"[^a-z0-9_-]+", "-", a.slug.lower()).strip("-")
    p = cfg.ROOT / "projects" / slug
    if p.exists():
        print(f"{p} already exists; not touching it. Files: {', '.join(sorted(x.name for x in p.iterdir()))}")
        return 1
    name, fmt, length, grade = RECIPES[a.recipe]
    fmt = a.format or fmt
    import build
    build.scaffold_files(p, 1080, 1920)
    (p / "media").mkdir()
    title = a.title or slug.replace("-", " ").title()
    (p / "brief.md").write_text(f"""# Brief: {title}

<!-- Filled from /new-video; answer the open lines before /plan. -->
- **Type:** {name} (recipe: docs/recipes/{a.recipe}.md)
- **Goal & audience:**
- **Platform & sizes:** {fmt}
- **Length:** {length}
- **Language(s):** {a.lang} (VO: {a.lang}, captions: {a.lang})
- **Assets:** (files in inbox/ or media/; stock: yes/no)
- **Music:** (file / library mood "…" / none)
- **Style references:** (links, colours, fonts){f" · brand kit: {a.brand}" if a.brand else ""}
- **Must include (exact text):** (dates, venues, handles, slogans: only from the user or the brand kit)
- **Avoid:**
- **Use Gemini (via Antigravity) for:** (best moments / music feel / render review / no)
- **Show me the plan before building:** yes

Created {time.strftime("%Y-%m-%d %H:%M")}.
""", encoding="utf-8")
    (p / "plan.md").write_text(f"""# Plan: {title}

Status: DRAFT (waiting for approval). Recipe: {a.recipe}. Format: {fmt}. Default grade: {grade}.

## Concept
(one paragraph: what the viewer feels and does)

## Structure and timings
| # | Time | Content | Music | Cut anchor |
|---|---|---|---|---|

## Music
(track, licence, which part (from → to), why; beat grid reliable?)

## Shots
| Clip | Source + in-point | Why | Treatment (speed, crop, grade, fx) |
|---|---|---|---|

## On-screen text (every language)
| Time | mr | hi | en | Style |
|---|---|---|---|---|

## VO script
(lines, voice, language)

## Transitions and effects

## Aspect ratios / exports

## Credits needed

## Open questions for the user
""", encoding="utf-8")
    print(f"created {p}\n  brief.md (fill in), plan.md (skeleton), media/\nnext: fill the brief, then /plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())

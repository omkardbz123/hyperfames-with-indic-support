---
description: Start a new video project from a recipe and fill in the brief
argument-hint: <slug> [recipe]
---
1. Run `uv run tools/new_video.py $ARGUMENTS` (recipe defaults to `promo`; list: `docs/recipes/README.md`).
2. Read the recipe file and `projects/<slug>/brief.md`. Ask the user only for what the brief still misses
   (goal, platform/sizes, length, languages, assets, music, must-include facts, avoid, Gemini use), in one short message.
3. Write their answers into `brief.md`. Facts (dates, venues, handles) only from the user or the brand kit.
4. Next step: `/ingest` for their files, then `/analyze`, then `/plan`.

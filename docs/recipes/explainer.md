# Explainer / motion graphics / infographic

## Inputs
- A script (or bullet points to turn into one with `agy`), numbers/data, icons/logos, language(s).

## Analysis
- VO lines → MMS word timings (generated at build). Music: calm bed (`music_library.py find "uplifting corporate"`).

## Structure
Hook question → 3–5 points (one idea per scene, 4–8 s each) → summary → call to action.

## Techniques
- Scenes as colour cards (`{"color": "#0C0C0E"}`) or footage, with `text` items: `"style": "title"` for the point, `"subtitle"` for detail, `"anim": "words"` synced to VO word times for key phrases.
- HyperFrames catalog blocks for charts, counters, 3D text, maps: install with `uv run tools/hf.py add <block>` inside the project and mount it as a sub-composition (search `uv run tools/hf.py catalog "<what>"`). Keep their timing on the main timeline.
- Captions from VO in `pop` style; `push`-type transitions (`whip`) between points.

## Defaults
`format: reels` or `youtube`, colour cards in brand colours, captions on.

## QA specifics
- Numbers on screen match the script; every claim's source noted in `plan.md`.
- Text stays on screen ≥ reading time (≈ 3 words/s + 0.5 s).

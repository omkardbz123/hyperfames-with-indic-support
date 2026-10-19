---
description: Run the cached local analysis for a project's assets (audio, video, transcript, photos)
argument-hint: <slug> [asset|all]
---
For each asset in `projects/<slug>/assets.json` (or the given file):
- music/audio: `uv run tools/analyze_audio.py <file>` → look at `audio.png`; note `beat_grid_reliable`, drops, sections.
- video: `uv run tools/analyze_video.py <clip>` → **look at `sheets/contact.jpg`**; for many clips also `uv run tools/index_footage.py <folder>`.
- speech: `uv run tools/transcribe.py <file> --lang mr|hi|en [--mode mixed] [--text-file script.txt]`; flag `low_conf` words to the user.
- photos: `uv run tools/analyze_photos.py <folder> --sheet _previews/photos.jpg` → look at the sheet (blur, duplicates, upscaling needed).
Ask Gemini (`/perceive`) only when the recipe needs moments/feel. Summarise what you learned in 5–10 lines.

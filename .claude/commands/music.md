---
description: Add tracks to or search the music library
argument-hint: add <file|folder> [--preset incompetech] | find "<mood>" [--bpm 90-110]
---
Run `uv run tools/music_library.py $ARGUMENTS`.
- `add` needs a licence (`--preset incompetech`, `--license …`, or a `.license.json` from `/stock`); it refuses otherwise.
- `find` ranks by CLAP mood match after the BPM/length filters; play nothing, just report title, BPM, key, licence, and why it fits.

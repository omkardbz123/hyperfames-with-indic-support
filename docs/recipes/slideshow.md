# Photo slideshow / memories

Weddings, birthdays, festivals, trips.

## Inputs
- A folder of photos (phones: EXIF rotation handled), a music track by mood, titles/dates.

## Analysis
1. `uv run tools/analyze_photos.py <folder> --sheet _previews/photos.jpg` → blur, duplicates (`keep`), faces, Ken Burns `focus`, whether a 9:16 crop needs upscaling. Look at the sheet; drop blurred and duplicate photos.
2. Upscale soft keepers: `uv run tools/fx.py upscale <photo> <out>` (x4plus, ~13 s each).
3. `music_library.py find "warm nostalgic acoustic" --min 60`; `analyze_audio.py` → phrases/sections.

## Structure
Photos in story order (time taken, or grouped by people/place); 2–4 s each, cut on downbeats/phrases (`beat_grid_reliable` false → phrase pacing); title card first; date/location `lower` texts; closing photo held longer.

## Techniques → EDL
- Photo clips with `"kenburns"` (alternate zoom in / out, focus on faces).
- Transitions: `fade` (0.6–0.8 s) mostly, `light-leak` shader for chapter changes.
- Grade: `warm_film`; optional film grain overlay (HyperFrames catalog) for memories.
- Music fade-out over the last 2 s (`fade_out`).

## Defaults
`format: reels` or `youtube`, 2.5–3.5 s per photo, `grade: warm_film`.

## QA specifics
- No photo shown sideways; faces never cropped by the Ken Burns frame; no soft upscales (build warns).

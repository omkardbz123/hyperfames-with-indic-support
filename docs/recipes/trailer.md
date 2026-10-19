# Cinematic trailer / teaser

## Inputs
- Footage with drama (motion, faces), a cinematic track (riser → hit → silence → drop), title text, date.

## Analysis
- `analyze_audio.py`: find the riser end, hits, the silence and the drop. `analyze_video.py` + `search_footage.py` for hero shots. Optional `/perceive <clip> find_moments`.

## Structure
Slow build (long shots, dark) → title card 1 on a hit → faster cutting → **silence (0.5–1 s, black or freeze)** → drop with a fast montage → title / date card → logo.

## Techniques → EDL
- Letterbox: a colour overlay is not built-in; use `"format": {"w": 1920, "h": 1080}` with footage cropped `{"y": 0.5}` and black bars via `"text"`-free colour cards, or render 2.39:1 inside 16:9 with the HyperFrames catalog letterbox block.
- Title cards: colour clips with `"text"` (`"style": "big"`, `"anim": "fade"`, Playfair/Anton), `dip` transitions.
- Sound design: `"sfx"`: braam on title cards, impact on hits, reverse_swell into the drop, `rides` for the silence.
- Grade: `teal_orange` or `cool_night`; `cinematic-zoom` shader into the montage.
- Speed ramps with RIFE on hero moments.

## Defaults
`format: youtube` (also export `reels` as a layout variant), `grade: teal_orange`.

## QA specifics
- The silence is real silence (music ride ≤ -24 dB) and the drop lands on the cut (±1 frame).

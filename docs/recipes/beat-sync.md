# Beat-sync montage

Phonk, sigma/aura, AMV, car, gym, sports, travel edits: footage cut tight to a rhythmic track.

## Inputs
- 5–40 clips (own footage, `/stock`, or user-supplied), one rhythmic track (library or user's; licence known).
- Optional: a mood/look reference ("black and white, aggressive", "warm travel").

## Analysis
1. `uv run tools/analyze_audio.py <track>` → `audio.json` + `audio.png` (look at it). Check `beat_grid_reliable`, `drops`, `hits`, kick/snare onsets, `sections`.
2. `uv run tools/analyze_video.py <clip>` for every clip → shots, motion, sharpness, best frames; look at each `contact.jpg`.
3. `uv run tools/index_footage.py <folder>` then `search_footage.py "car drifting at night" --sheet` to find shots by description.
4. Optional Gemini (`/perceive <track> music_feel`, `/perceive <clip> find_moments`) to rank moments, never for timing.
5. Pick the music window: `uv run tools/snap.py grid audio.json --from <t0> --to <t1> --on kick --offset <from>` lists the anchors.

## Structure (15–20 s example)
| Part | Music | Cutting |
|---|---|---|
| Hook 0–2 s | intro / pre-drop | 1–2 shots, title slam |
| Build | low section, riser | cuts every 2 beats (downbeats), speed ramp into slow-mo |
| Drop | first kick after the silence | flash + boom + zoom punch + shake, then cuts on every kick |
| Out | phrase end | hold the best shot, fade or tape-stop |

## Techniques → EDL
- Cuts `"snap": {"to": "kick"}` in drum sections, `"downbeat"` in sparse parts, `"drop"` for the hit.
- One speed ramp: `"ramp": [{"dur": 0.5, "speed": 1}, {"dur": 1.5, "speed": 0.25, "rife": true}, {"speed": 1}]`.
- Silence before the drop: music `"rides": [{"from": drop-0.5, "to": drop-0.03, "db": -24}]`, plus `"sfx": riser (ends on the drop), boom`.
- On the drop: `"transition": {"type": "flash"}` or `"flashes"`, `"fx": zoom_punch + shake`.
- ≤2 shader transitions per video (glitch, chromatic-split, whip-pan, cinematic-zoom); the rest hard cuts.
- Grade: `bw_contrast` (phonk/sigma) or `teal_orange` (cars/travel). Minimal text (`"anim": "slam"`).
- Text at most 2–3 words on screen.

## Defaults
`format: reels`, 30 fps, `grade: bw_contrast`, no captions, export `reels` + `whatsapp`.

## QA specifics
- Every cut within ±1 frame of its anchor (`/review` checks build.json anchors against detected cuts).
- No cut lands inside a fade-in of the music.
- Copyrighted clips/music can be muted or flagged on Instagram; prefer library/CC music.

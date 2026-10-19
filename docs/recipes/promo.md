# Promo / ad / event invite / announcement

The GoaALM style: a story that ends in a call to action and an end card with the event facts.

## Inputs
- Brand kit (`library/brands/<brand>/brand.json`): colours, fonts, handle, event facts. **Facts only from the kit or the user.**
- Script (the user's, or drafted with `agy` text tasks and approved), language(s): mr / hi / en.
- Photos/footage (own, `/stock`), a music track with a change of mood (sombre → triumphant), or two tracks.

## Analysis
- `analyze_audio.py` on the music (sections, drops, energy); `analyze_photos.py <folder> --sheet` (faces, blur, duplicates, Ken Burns focus); `analyze_video.py` on clips.
- VO: `voiceover.py` lines are generated during `/build`; word timings come from MMS alignment (not edge-tts).

## Structure (30 s)
| Act | Time | Content |
|---|---|---|
| Hook | 0–3 s | strongest image + 2–4 word title |
| Problem | 3–12 s | sombre grade (`bw_contrast`), slow Ken Burns, VO lines |
| Turn | ~12 s | music silence + boom, flash or dip |
| Hope / call | 12–24 s | warm grade (`warm_film`/`teal_orange`), faster cuts, kinetic captions |
| End card | last 4–6 s | brand end card: name, date · time, route/venue, handle |

## Techniques → EDL
- `"vo"` with one line per sentence; `"captions": {"src": "vo", "style": "kinetic", "max_words": 2-3}` (Devanagari works).
- Per-act grade: set `grade` per clip. Music sections: two `music` entries are not supported, so pick one track with a turn, or ride the bed (`rides`).
- Titles in the brand fonts (`"style": "title"`/`"quote"`), `"anim": "rise"`/`"words"` synced to VO words.
- `"brand": "<brand>", "endcard": {"at": D-5, "until": D}`.
- Light leak or `fade` between acts; `dip` into the end card.

## Defaults
`format: reels`, `grade: warm_film`, captions kinetic in the brand caption font, music ducked under VO (-9 dB), export `reels` + `whatsapp` + `feed45`.

## QA specifics
- **Every event fact checked against the brand kit / user**; export refuses while `to_confirm` is non-empty.
- Devanagari spelling against the script; no missing glyphs.
- Captions within ±80 ms; VO intelligible over music (ducking).

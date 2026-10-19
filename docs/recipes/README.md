# Recipes

One file per edit type. Each says: **inputs → analysis → structure → techniques (EDL features) → defaults → QA**.
`/new-video <slug> --recipe <name>` copies the recipe's defaults into `brief.md` / `plan.md`;
`/plan` writes `edl.json` following it (schema: `docs/CONTRACTS.md` → edl.json).

| Recipe | File | Typical length | Default format |
|---|---|---|---|
| Beat-sync montage (phonk, sigma, AMV, car, gym, sports, travel) | [beat-sync.md](beat-sync.md) | 10–30 s | reels |
| Promo / ad / event invite / announcement | [promo.md](promo.md) | 20–60 s | reels |
| Talking head → short reels | [talking-head.md](talking-head.md) | 15–60 s | reels |
| Lyric video (mr/hi/en) | [lyric.md](lyric.md) | song | reels / youtube |
| Photo slideshow / memories | [slideshow.md](slideshow.md) | 30–120 s | reels / youtube |
| Explainer / motion graphics | [explainer.md](explainer.md) | 30–90 s | reels / youtube |
| Cinematic trailer / teaser | [trailer.md](trailer.md) | 20–60 s | youtube / reels |
| Tutorial / screen recording | [tutorial.md](tutorial.md) | 1–10 min | youtube |
| Subtitles, translation, dubbing | [subtitles-dub.md](subtitles-dub.md) | any | source |
| Vlog / event recap / mini-doc | [recap.md](recap.md) | 1–10 min | youtube |
| Restoration / enhancement | [restoration.md](restoration.md) | any | source |
| Memes / green screen / templates | [meme.md](meme.md) | 5–30 s | reels / square |
| Multi-format repurpose | [repurpose.md](repurpose.md) | any | all |

## Rules every recipe follows

- **Timing comes from local analysis** (`audio.json`, `video.json`, `transcript.json`), never from Gemini. Gemini (via `agy`) only ranks moments, judges feel, reviews renders.
- **Cuts snap** (`"snap": {"to": "kick"|"beat"|"downbeat"|"hit"|"drop"|"onset"|"word"}`) when the music grid is reliable; otherwise pace by phrases/sections (`beat_grid_reliable: false`).
- **Text is Chrome-rendered** with library fonts; Devanagari text automatically gets a Devanagari font (Mukta/Hind/…; never Yatra One with conjuncts).
- **Safe zones** (Reels 1080×1920): nothing important in the top 220 px, bottom 400 px, right 120 px.
- **Credits**: every asset needs a licence (sidecar or library index); exports ship `CREDITS.txt` and a caption credit line.
- **Facts** (dates, venues, handles) only from the brand kit or the user; `to_confirm` blocks export.
- Show `plan.md` to the user and wait for approval before `/build`.

## EDL feature cheat-sheet

| Want | EDL |
|---|---|
| cut on a beat | clip `"snap": {"to": "beat", "tol": 0.12}` |
| speed ramp with real slow motion | `"ramp": [{"dur": 0.6, "speed": 1}, {"dur": 1.4, "speed": 0.25, "rife": true}, {"speed": 1}]` |
| shader transition | `"transition": {"type": "glitch"|"whip-pan"|"cinematic-zoom"|"flash-through-white"|"light-leak"|"chromatic-split"|…, "dur": 0.4}` |
| CSS transition | `"transition": {"type": "fade"|"dip"|"flash"|"zoom"|"whip", "dur": 0.4}` |
| zoom punch / shake on a hit | `"fx": [{"type": "zoom_punch", "at": 8.2, "amount": 1.15}, {"type": "shake", "at": 8.2, "dur": 0.3}]` |
| slow push-in | `"fx": [{"type": "push_in", "to": 1.08}]` |
| Ken Burns on a photo | `"kenburns": {"from": 1.0, "to": 1.12, "focus": [0.5, 0.4]}` (focus defaults to the face/saliency point) |
| reframe 16:9 → 9:16 | `"crop": "track"` (subject tracking) or `{"x": 0.4}` |
| grade | top-level `"grade": "bw_contrast"` or per clip; LUTs in `library/luts` |
| white flash on the drop | `"flashes": [{"at": 8.196, "dur": 0.3}]` |
| silence before the drop | music `"rides": [{"from": 7.6, "to": 8.15, "db": -24}]` |
| SFX | `"sfx": [{"name": "riser", "at": 8.196}, {"name": "boom", "at": 8.196}]` (risers END on `at`) |
| voiceover | `"vo": {"lang": "mr", "voice": "mr_f", "lines": [{"id": "l01", "text": "…"}], "start": 0.5, "gap": 0.35}` |
| captions | `"captions": {"src": "vo"|"clips"|"<transcript.json>", "style": "kinetic"|"pill"|"pop", "max_words": 3}` |
| meme lettering | text `"style": "meme"` (white, thick black outline); stickers: `"style": "tag", "bg": "#FF4F9A", "rotate": -4` |
| darken a busy picture under text | clip `"dim": 0.4` |
| titles | `"text": [{"content": "…", "at": 1, "until": 3, "style": "title"|"big"|"subtitle"|"tag"|"lower"|"quote", "anim": "slam"|"pop"|"rise"|"fade"|"type"|"words", "pos": "center"|"top"|"bottom"|"lower"}]` |
| brand end card | `"brand": "goaalm", "endcard": {"at": 26, "until": 30}` |
| keep the clip's own sound | clip `"audio": true` (or `{"gain_db": -3}`) |

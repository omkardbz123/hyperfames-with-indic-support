# Vegan Bawaal: post templates

Brand kit: `brand.json` (lime `#B8F53A` + pink `#FF4F9A` on ink `#121212` / cream `#FFF8EC`; Anton + Poppins, Baloo 2 + Mukta for Devanagari; Hinglish captions in Baloo 2, `pop` style). Preview of all three formats: `projects/_test-veganbawaal/` (`renders/draft.mp4`).

**Voice:** Hinglish, funny but kind. Jokes hit industries, habits and myths, never people or communities. Every post ends with one easy action (follow, try a swap, show up, share). Claims need a source in the caption.

Use them by asking: *"Make a Vegan Bawaal meme with inbox/cow.jpg: top 'जब कोई बोले', bottom '"thoda sa ghee chalega"'"*. Claude builds the EDL from the matching block below.

## 1. Meme (4–7 s, Reel or still)

```jsonc
"brand": "veganbawaal", "duration": 5, "grade": "none",
"clips": [{"id": "pic", "src": "inbox/<photo or clip>", "at": 0, "kenburns": {"from": 1.0, "to": 1.06}}],
"text": [
  {"content": "<setup>",     "at": 0.2, "until": 5, "style": "meme", "anim": "pop", "pos": "top"},
  {"content": "<punchline>", "at": 1.0, "until": 5, "style": "meme", "anim": "pop", "pos": "bottom", "size": 96}
],
"music": {"src": "<library track>", "gain_db": -6}, "sfx": [{"name": "ding", "at": 1.0, "gain_db": -10}]
```
Timing: the punchline lands 0.8–1.2 s after the setup (or on a beat / a spoken word with `snap`).

## 2. Myth vs fact (8–10 s)

```jsonc
"clips": [{"id": "card", "color": "#121212", "at": 0}],
"text": [
  {"content": "MYTH", "style": "tag", "bg": "#FF4F9A", "rotate": -4, "pos": "abs", "top": 560, "at": 0.3, "until": 9, "anim": "pop"},
  {"content": "<the myth>", "style": "title", "pos": "abs", "top": 680, "at": 0.5, "until": 9, "anim": "rise"},
  {"content": "FACT", "style": "tag", "rotate": 3, "pos": "abs", "top": 1010, "at": 2.5, "until": 9, "anim": "pop"},
  {"content": "<the fact, 1 line + source in the caption>", "style": "subtitle", "pos": "abs", "top": 1120, "at": 2.7, "until": 9, "anim": "rise"}
],
"endcard": {"at": 9, "until": 10.5}
```
Optional: a VO reading both lines (`"vo"`, Hindi or English) with `"captions": {"src": "vo"}`.

## 3. Event promo / collab (10–30 s)

```jsonc
"clips": [{"id": "hero", "src": "<event or protest photo/clip>", "at": 0, "dim": 0.4, "kenburns": {"from": 1.1, "to": 1.0}}, ...],
"text": [
  {"content": "VEGAN BAWAAL × <partner>", "style": "tag", "pos": "top", "size": 46, "at": 0.1, "until": 3, "anim": "pop"},
  {"content": "<CALL, e.g. WALK WITH US>", "style": "big", "anim": "slam", "at": 0.3, "until": 3},
  {"content": "<event · date · city>", "style": "subtitle", "pos": "bottom", "at": 0.6, "until": 3, "anim": "rise"}
],
"endcard": {"at": <end - 2>, "until": <end>}
```
Event facts (date, time, venue, route, handles) come **only from the organisers / their brand kit** (e.g. `goaalm`); post as an Instagram collab with them.

## Tips
- `dim` (0–0.5) darkens a busy photo under big text; captions get a soft scrim automatically.
- Hooks over unknown footage: `tag` style (solid pill) instead of plain text.
- Devanagari: Baloo 2 / Mukta only (Hind shows Latin-looking digits, Yatra One breaks conjuncts).

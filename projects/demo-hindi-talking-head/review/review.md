# Review: Hindi talking-head reel (demo)

Render: `master.mp4` · 2026-10-19T17:19:43 · **FAIL** (1 fail, 1 warn)

| Check | Status | Detail |
|---|---|---|
| technical | pass | 1080x1920 30 fps h264 yuv420p, 26.04s, 11.1 Mb/s, audio yes |
| loudness | pass | -13.8 LUFS, TP -3.8 dBTP, LRA 1.7 |
| black | pass | no black frames |
| freeze | pass | no frozen picture |
| cut_sync | warn | 5/6 snapped cuts within ±1 frame (worst 0.3 f); no clear picture change near: ['c02'] |
| captions | pass | 34 pages, no overlaps, words match the aligner |
| safe_zone | pass | 1 text block(s) inside the safe zone (top 220, bottom 400, left 60, right 120 px) |
| glyphs | pass | 35 text(s) checked: every character exists in its font |
| facts | pass | no unconfirmed brand facts |
| licences | fail | unknown licence: hindi_cut.mp4 |
| hyperframes | pass | lint, runtime, layout and contrast clean |

## Fix list
- licences: ask the user (own footage -> tools/ingest.py --own), or add <file>.license.json
- cut_sync: the render's cut moved away from its beat: rebuild from edl.json (don't hand-edit index.html)

Contact sheet: `review/sheet.jpg` (look at it).

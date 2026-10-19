# Review: GoaALM Marathi promo (demo)

Render: `master.mp4` · 2026-10-19T17:19:18 · **PASS** (0 fail, 1 warn)

| Check | Status | Detail |
|---|---|---|
| technical | pass | 1080x1920 30 fps h264 yuv420p, 30.00s, 19.5 Mb/s, audio yes |
| loudness | pass | -14.1 LUFS, TP -2.4 dBTP, LRA 2.4 |
| black | pass | 1 dark stretch(es), all intended |
| freeze | pass | 1 still stretch(es), none inside video clips |
| cut_sync | pass | 3/3 snapped cuts within ±1 frame (worst 0.4 f) |
| captions | pass | 21 pages, no overlaps, words match the aligner |
| safe_zone | pass | 2 text block(s) inside the safe zone (top 220, bottom 400, left 60, right 120 px) |
| glyphs | pass | 26 text(s) checked: every character exists in its font |
| facts | warn | to confirm with the user: exact December date (day); handle @goaalm; logo file (none yet); Marathi/Hindi names above; Marathi/Hindi end-card wording (end_card_mr / end_card_hi) |
| licences | pass | 13 asset(s), all licensed |
| hyperframes | pass | lint, runtime, layout and contrast clean |

## Fix list
- facts: confirm with the user, update library/brands/<brand>/brand.json (to_confirm)

Contact sheet: `review/sheet.jpg` (look at it).

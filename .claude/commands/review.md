---
description: QA a render: automated checks + contact sheet (+ optional Gemini watch-through)
argument-hint: <slug> [--gemini]
---
1. Run `uv run tools/review.py projects/<slug> $ARGUMENTS` (`--gemini` adds an agy review_render, ~2.5 min).
2. **Look at `projects/<slug>/review/sheet.jpg`** yourself: cuts, titles, captions, end card, spelling (Devanagari too).
3. Every FAIL: fix it in `edl.json` (never hand-edit index.html), rebuild, re-render, review again.
4. Gemini notes are advisory: check each against the render before acting.
5. Give the user a short verdict + what you changed.

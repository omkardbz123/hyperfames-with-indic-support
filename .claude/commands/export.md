---
description: Export a reviewed project to platform presets with credits and caption
argument-hint: <slug> [presets]
---
1. Run `uv run tools/export.py projects/<slug> --presets <list, default reels,whatsapp>` (presets: reels, shorts, feed45, square, youtube, whatsapp, master).
2. If it refuses because brand facts are unconfirmed: ask the user to confirm them (exact date, handle, names) and update
   the brand kit; only use `--force-unconfirmed` for a labelled draft. Unknown licences: ask the user, never `--allow-unknown` for a post.
3. Show `exports/<slug>/report.md` highlights and the poster; give the `caption.txt` text ready to paste.

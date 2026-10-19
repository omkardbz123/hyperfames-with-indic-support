---
description: Show, check or create a brand kit
argument-hint: <brand> | new <brand> --name "…"
---
`uv run tools/brand.py show|check <brand>` or `new <brand> --name "…" [--handle @x] [--accent #RRGGBB]`.
Event facts (date, time, venue, route, handle) come only from the user; keep anything unconfirmed in `to_confirm`
(export refuses until it is empty). Ask for a logo file (PNG/SVG with transparency) if there is none.

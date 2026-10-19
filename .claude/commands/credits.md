---
description: Regenerate CREDITS.txt and the caption credit line for a project
argument-hint: <slug>
---
Run `uv run tools/credits.py projects/<slug> --out exports/<slug>` and show the caption line.
It fails on assets without a licence: ask the user (own footage → `/ingest --own` after their yes).

---
description: Check every tool, model, path and login of the studio and print fixes
---
Run `uv run tools/doctor.py` from the studio root and show the table.
- For every FAIL, explain the fix in one line and offer to do it (ask before installing anything over 2 GB).
- ⛔ USER rows (logins, API keys, the leaked GEMINI_API_KEY) are the user's to do: say exactly what to click or type.
- Never print secrets. Never use the Gemini API even if a key is set.

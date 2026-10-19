---
description: Register files from inbox/ (or given paths) for a project, with licences
argument-hint: <slug> [files...]
---
1. Run `uv run tools/ingest.py <files or nothing for inbox/> --project projects/<slug>`.
2. For files listed without a licence: **ask the user** whether they shot/own them. Only after a clear yes run again
   with `--own --author "<their name>"`; for third-party files record `--license … --author … --source …`.
3. Report awkward formats that got a usable copy (VFR → CFR, HEIC → JPEG).

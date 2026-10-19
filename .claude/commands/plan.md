---
description: Write plan.md and edl.json for a project, then stop for the user's approval
argument-hint: <slug>
---
1. Read `projects/<slug>/brief.md`, the recipe in `docs/recipes/`, the EDL cheat-sheet (`docs/recipes/README.md`),
   the `edl.json` schema (`docs/CONTRACTS.md`), the analysis of every asset, and the brand kit if any.
2. Choose the music window and list anchors: `uv run tools/snap.py grid analysis/<id>/audio.json --from <t0> --to <t1> --on kick|beat|downbeat --offset <music from>`.
3. Write `plan.md`: concept, structure with timings, music choice and why, shot list, on-screen text in every language,
   VO script, transitions/effects, aspect ratios, credits needed, open questions.
4. Write `edl.json` and validate it: `uv run tools/edl.py projects/<slug>` (fix errors; check the snapped cut list).
5. **Stop.** Show the user the plan (short) and wait for approval or changes before `/build`.

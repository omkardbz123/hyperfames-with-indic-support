# Vlog / event recap / mini-documentary (longer form)

## Inputs
- Many clips from an event or trip (often hours), optional interviews, music beds.

## Analysis
1. `index_footage.py <folder>` and `analyze_video.py` on all clips (shots, motion, faces, sharpness).
2. Story outline: `/perceive <clip> describe` per chunk (Gemini), then you draft chapters in `plan.md`.
3. Interviews: `transcribe.py`; pick quotes with `agy` text tasks.

## Structure
Cold open (best moment, 5 s) → title → chapters (arrival / main event / people / ending), each 30–90 s with a music bed per chapter → closing quote → credits.

## Techniques → EDL
- J/L cuts: interview `"audio": true` clips that start before / end after the picture (place b-roll clips over them on later `at` with the interview clip continuing in sound only: use a separate `music`-free audio clip via `sfx` `src` for the overlap).
- Chapter titles: `"text"` `"style": "title"`, `dip` transitions.
- Shot selection by motion/faces/sharpness scores; SigLIP search for specific shots.
- Music beds: one per build (split long recaps into chapters built separately, or pick a track with section changes).

## Defaults
`format: youtube`, grade `warm_film`, captions only for interviews.

## QA specifics
- Pacing: no chapter longer than planned; faces in focus; consent for identifiable people when posting.

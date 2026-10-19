# Talking head → short reels

Podcasts, speeches, interviews, vlogs-to-camera: cut the best part, remove dead air, reframe, caption.

## Inputs
- A recording (often 16:9). Language mr / hi / en (mixed is fine: Flex mixed mode keeps English in Latin script).

## Analysis
1. `uv run tools/transcribe.py <clip> --lang hi [--mode mixed]` → `transcript.json` (words with times; check `low_conf`).
2. Highlight picking: `agy` text task on the transcript (+ audio energy) to propose 15–60 s segments; you choose.
3. `uv run tools/fx.py cut-silence <clip> <cut.mp4>` (auto-editor) on the chosen segment, or plan jump cuts in the EDL from word gaps.
4. Transcribe the cut file again (timings must match the cut) or use the EDL clip mapping (`captions.src: "clips"` maps the source transcript through each clip's in/out).
5. `uv run tools/track_subject.py <clip> --aspect 9:16 --debug review.mp4` → check the crop follows the face.

## Structure
Hook title in the first 2 s (the strongest line, as `text`), then the segment with captions, zoom punch-ins on emphasis words, optional b-roll (SigLIP search or stock) over long explanations, end card or handle.

## Techniques → EDL
- Jump cuts: several clips from the same source with consecutive `in` points, `"audio": true`, `"crop": "track"`.
- Captions: `"captions": {"src": "clips", "style": "pop"|"kinetic", "max_words": 3}`.
- Emphasis: `"fx": [{"type": "zoom_punch", "at": <word start>, "amount": 1.12, "dur": 0.35}]` (alternate punched/un-punched clips for a two-camera feel: `push_in`).
- Music bed optional, low (`gain_db: -6`), ducked automatically on caption words.
- `voice` denoise first if needed: `fx.py denoise-voice`.

## Defaults
`format: reels`, no grade (or `faded_matte`), captions `pop`, export `reels` + `shorts`.

## QA specifics
- Caption words ±80 ms; no caption pages overlapping; captions clear of the face and the bottom 400 px.
- No mid-word cuts (cut points at word gaps ≥ 120 ms).
- Reframe keeps the face inside the crop 100 % of the time.

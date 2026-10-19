# Tutorial / screen recording

## Inputs
- Screen recording(s) (often VFR from OBS/phone: `/ingest` makes a CFR copy), voice track, step list.

## Analysis
- `transcribe.py` on the voice; `fx.py cut-silence` for dead air; `analyze_video.py` for scene changes (window switches).

## Structure
Title → what you'll learn → steps (title per step) → result → recap.

## Techniques → EDL
- Zoom-ins on the action area: clip `"crop": {"x": 0.7, "y": 0.3}` on a duplicated clip, or `push_in` with `transformOrigin` (crop is cleaner: real pixels).
- Step titles: `"text"` `"style": "tag"`, `"pos": "top"`.
- Captions from the voice (`"src": "clips"`), style `pill`.
- Callouts/arrows: HyperFrames catalog `hw-arrow`, `hw-callout-circle` blocks.
- Keep `"audio": true` on the recording clips.

## Defaults
`format: youtube`, captions pill, no grade.

## QA specifics
- Text in the recording stays readable after scaling (zoom where it's small); no PII visible (passwords, emails, tokens): check snapshots.

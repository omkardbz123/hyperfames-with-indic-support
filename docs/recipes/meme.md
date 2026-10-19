# Memes / green screen / templates

## Inputs
- A clip (green screen or a person to cut out), a background, punchline text, optional SFX.

## Steps
- Green screen: `uv run tools/fx.py key <in> <out.mov>` (ProRes 4444 / WebM alpha).
- Person cutout (no green screen): `uv run tools/hf.py remove-background in.mp4 -o out.webm` (check edges: bright objects near the person can stay).
- Text behind subject: background clip → text → cutout clip on top (place the cutout as a later clip at the same `at`... not supported by the sequential EDL; build the layer in a HyperFrames sub-composition from the catalog (`caption-parallax-layers`, `mk-emphasis-type`) instead).

## Techniques → EDL
- Big top/bottom meme text: `"text"` `"style": "big"`, `"pos": "top"` / `"bottom"`, `"anim": "pop"`.
- Punchline timing on a beat or the speaker's word (`snap` / word times); SFX `ding`, `glitch`, `tape_stop`, `drop_808`.
- Zoom punch on the reaction.

## Defaults
`format: reels` or `square`, no grade.

## QA specifics
- Text legible on any background (shadow on); cutout edges clean.

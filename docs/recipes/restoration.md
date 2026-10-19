# Restoration / enhancement

## Inputs
- Old, shaky, noisy, low-res or interlaced footage/photos; noisy voice.

## Steps (Phase 6 toolkit, each `uv run tools/fx.py <cmd> -h`)
1. `deinterlace` (if combing), `stabilize`, `denoise-video` (hqdn3d), `denoise-voice` (80 Hz high-pass + DeepFilterNet3).
2. `upscale`: photos with x4plus (~13 s/frame); video with animevideov3 (~0.4 s/frame; real footage: try a short test first). Never x4plus on whole videos.
3. `slowmo --keep-fps` to raise frame rate (RIFE), colour: `lut` (`faded_matte` → neutral) or a grade.
4. Before/after split: an EDL with two clips of the same timing cropped `{"x": 0.25}` / `{"x": 0.75}` is possible; simpler: alternate before/after shots with `fade`.

## Defaults
Keep the source aspect and fps; export `master` + `youtube`.

## QA specifics
- Compare before/after snapshots; no over-sharpening halos; voice not robotic after denoise (listen).

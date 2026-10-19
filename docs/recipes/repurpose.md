# Multi-format repurpose

One master project → 9:16, 4:5, 1:1, 16:9 versions with layouts per format (not naive crops).

## How
- Build the master in its main format (`edl.json` `format`).
- `uv run tools/export.py projects/<slug> --presets reels,feed45,square,youtube`: presets with the same aspect as the master are transcoded from the master render; other aspects are rebuilt as **layout variants** (`tools/build.py --format <fmt>` → `projects/<slug>/variants/<fmt>/`): footage is re-framed for the new aspect (`"crop": "track"` follows the subject; fixed crops keep their focus point), text positions and caption sizes follow that format's safe zones.
- Check every variant's contact sheet: text that fit 9:16 may wrap in 1:1.

## Safe zones
| Format | Keep clear |
|---|---|
| Reels/Shorts 1080×1920 | top 220, bottom 400, right 120 |
| Feed 4:5 1080×1350 | ~5 % margins |
| Square 1080×1080 | ~5 % margins |
| YouTube 1920×1080 | 7 % top, 9 % bottom (captions/controls) |

## QA specifics
- `/review` on every variant; loudness identical across versions (same mix).

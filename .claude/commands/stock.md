---
description: Search free stock (Openverse, Wikimedia Commons; Pexels/Pixabay with keys) and import picks
argument-hint: "<query>" [photo|video|audio]
---
1. `uv run tools/stock.py search "<query>" --kind <photo|video|audio> [--portrait] --sheet` → **look at `_previews/stock.jpg`**.
2. Pick with the user (or by the brief), then `uv run tools/stock.py get <provider>:<id>` (writes the file + `.license.json`).
3. Only CC0 / PD / CC BY / CC BY-SA (+ Pexels/Pixabay licences) are accepted; CC BY-SA makes the video share-alike: say so.

---
description: Build the approved EDL into a HyperFrames project and render a draft
argument-hint: <slug>
---
1. Only after the user approved `plan.md`.
2. Run `uv run tools/build.py projects/<slug> --render` (prep is cached; first builds with RIFE/VO take longer).
3. Read the build warnings (soft photos, unreliable beat grid, unconfirmed facts) and pass them on.
4. Then run `/review`.

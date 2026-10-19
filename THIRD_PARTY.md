# Third-party components

This repo is the studio's own code, docs and settings, plus a few vendored files. Large tools and models are **not** in the repo: `installation.bat` / `tools/setup.py` download them from their official sources and check their SHA-256 fingerprints.

## Included in this repo

| What | Where | Licence |
|---|---|---|
| HyperFrames agent skills | `.claude/skills/*` (except `studio/`), from [heygen-com/hyperframes](https://github.com/heygen-com/hyperframes) (`skills-lock.json`) | Apache-2.0, as HyperFrames |
| HyperFrames shader-transitions 0.8.172 | `library/vendor/shader-transitions-0.8.172/` | Apache-2.0 (LICENSE included) |
| GSAP 3.14.2 | `library/vendor/gsap-3.14.2/` | GSAP Standard "no charge" licence, https://gsap.com/standard-license |
| Music by Kevin MacLeod: "B-Roll", "Club Diver", "Go Cart - Drop Mix" | `library/music/incompetech/` | CC BY 4.0. The credit line is in `library/music/index.json`; `tools/credits.py` adds it to every export. |
| Two freesound.org tracks by prospekt42 | `library/stock/openverse/` | CC0 (sidecar `.license.json`) |
| Colour LUTs, synthesised SFX | `library/luts/`, made by `tools/sfx.py` | own work |

## Downloaded at setup (not in the repo)

| What | Source | Licence |
|---|---|---|
| HyperFrames 0.8.172 (npm) | npmjs.com/package/hyperframes | Apache-2.0 |
| FFmpeg full build | gyan.dev (winget `Gyan.FFmpeg`) | GPL-3.0 |
| RIFE ncnn Vulkan 20250112 | github.com/TNTwise/rife-ncnn-vulkan | MIT |
| Real-ESRGAN ncnn Vulkan v0.2.5.0 | github.com/xinntao/Real-ESRGAN | BSD-3-Clause |
| DeepFilterNet 0.5.6 | github.com/Rikorose/DeepFilterNet | MIT / Apache-2.0 |
| auto-editor 29.3.1 | github.com/WyattBlue/auto-editor | Unlicense |
| Indic-Transcribe-Flex (OpenVINO int8) | huggingface.co/omkar9896/indic-transcribe-openvino-int8, converted from bodhan-ai/indic-transcribe-flex | Indic Open Model License v1.0. Credit: "Built with Indic-Transcribe-Flex from Bodhan AI / AI4Bharat." |
| Parakeet TDT 0.6B v3 | NVIDIA (via `hyperframes models install parakeet`) | CC-BY-4.0 |
| MMS-300m forced aligner | huggingface.co/MahmoudAshraf/mms-300m-1130-forced-aligner | CC-BY-NC-4.0 (non-commercial) |
| Beat This! | github.com/CPJKU/beat_this | MIT |
| CLAP (larger_clap_music_and_speech) | huggingface.co/laion | Apache-2.0 |
| SigLIP 2 base | huggingface.co/google/siglip2-base-patch16-224 | Apache-2.0 |
| htdemucs, BS-RoFormer (audio-separator) | github.com/nomadkaraoke/python-audio-separator | MIT |
| YuNet / MediaPipe BlazeFace, EfficientDet-Lite0 | opencv_zoo / Google MediaPipe | MIT / Apache-2.0 |
| Kokoro-82M | hexgrad/Kokoro-82M (via `hyperframes tts`) | Apache-2.0 |
| Google Fonts (Mukta, Noto, Hind, Tiro, Baloo 2, …) | github.com/google/fonts | SIL OFL 1.1 |

Python and Node packages: see `uv.lock` and `package-lock.json`.

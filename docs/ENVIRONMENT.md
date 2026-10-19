# Environment

Detected 2026-10-19 during Phase 0/1. Re-check any time with `uv run tools/doctor.py`.

## Machine

| Item | Value |
|---|---|
| OS | Windows 11 Home Single Language 10.0.26200 (Git Bash + PowerShell 5.1) |
| CPU / RAM | Intel Core Ultra 7 155H (22 threads) / 31 GB |
| NPU | Intel AI Boost (visible to OpenVINO as `NPU`; not used yet) |
| GPU | Intel Arc (iGPU). No NVIDIA. HyperFrames reports "hardware gpu" for Chrome capture; ncnn/Vulkan tools (RIFE, Real-ESRGAN) see it as device 0 with fp16. |
| Disk | C: 146 GB free, D: ~114 GB free. Caches live on D: (`cache/`). |

## Toolchain

| Tool | Version | Path / notes |
|---|---|---|
| Node / npm | v26.1.0 / 11.13.0 | system |
| Python (studio) | 3.11.6 | `.venv` via `uv venv --python 3.11` (uv-managed interpreter) |
| Python (system) | 3.11.9 default; `py` launcher default is 3.14.2; 3.12/3.13 also present | not used by the studio |
| uv | 0.9.30 | `~/.local/bin/uv` |
| git | 2.51.0.windows.2 | repo initialised on `main` |
| FFmpeg (pinned) | **8.0.1 full build (Gyan)** | `%USERPROFILE%\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.0.1-full_build\bin\` |
| Chrome (system) | installed | `C:\Program Files\Google\Chrome\Application\chrome.exe` |
| Chrome headless shell (render) | 152.0.7977.30 | `%USERPROFILE%\.cache\hyperframes\chrome\…` (from `hyperframes browser ensure`) |
| HyperFrames CLI | **0.8.172** (pinned in `package.json`) | `node_modules/.bin/hyperframes` — always run through `tools/hf.py` |
| Docker | 29.5.2 | installed, daemon not running (optional) |
| Antigravity app | installed | `D:\Program\Antigravity` (`antigravity` launcher on PATH). **`agy` CLI not installed** (Phase 5). |
| Gemini CLI | v0.57 | installed but **not used** (AI Pro moved to Antigravity CLI) |

### FFmpeg builds on PATH (correction to BUILD_PLAN §3)

The plan said two builds; there are **four**, in this PATH order:

1. `C:\ProgramData\chocolatey\bin\ffmpeg` — 8.0 essentials
2. `C:\ffmpeg\bin\ffmpeg` — 2025-09-28 git essentials
3. yt-dlp's `ffmpeg-N-121583` build (WinGet)
4. Gyan 8.0.1 **full** build (WinGet) ← pinned in `config/studio.toml`

HyperFrames on its own picks #1 from PATH. `tools/hf.py` sets `HYPERFRAMES_FFMPEG_PATH` / `HYPERFRAMES_FFPROBE_PATH` so it uses #4.

## Python packages (`.venv`)

numpy 2.4.6 · scipy 1.17.1 · opencv-python 5.0.0.93 · pillow 13.0.0 · soundfile 0.14.0 · librosa 0.11.0 · tqdm 4.70.1 · pydantic 2.14.1 · rich 15.0.0 · tomli-w 1.2.0

Phase 2: torch 2.14.1+cpu (PyPI's Windows wheel is CPU-only; no XPU) · torchaudio 2.11.0 (pinned by beat-this; imports fine with torch 2.14) · beat-this 1.1.0 · transformers 5.20.1 · audio-separator 0.47.0 (`[cpu]` extra) · onnxruntime 1.31.0 · edge-tts 7.3.1 · matplotlib 3.11.2 · einops · soxr · rotary-embedding-torch

## Install log

| Date | Phase | What | Command |
|---|---|---|---|
| 2026-10-19 | 0 | venv + base packages | `uv venv --python 3.11` then `uv sync` (deps in `pyproject.toml`) |
| 2026-10-19 | 1 | HyperFrames CLI 0.8.172 | `npm install` (package name `ai-video-studio`, avoids ENOSELF) |
| 2026-10-19 | 1 | HyperFrames skills (21) → `.claude/skills/` | `npx skills add heygen-com/hyperframes -a claude-code -s '*' -y --copy` (skills CLI 1.7.2; lock in `skills-lock.json`) |
| 2026-10-19 | 1 | Render browser | `uv run tools/hf.py browser ensure` → chrome-headless-shell 152.0.7977.30 |
| 2026-10-19 | 1 | 17 Google Fonts families (OFL) → `library/fonts/` | `uv run tools/fetch_fonts.py` |
| 2026-10-19 | 2 | Audio stack | `uv add torch beat-this einops soxr rotary-embedding-torch transformers "audio-separator[cpu]" edge-tts matplotlib` |
| 2026-10-19 | 2 | Beat This! `final0` (77 MB) + `small0` (8 MB) | auto-download → `cache/torch/hub/checkpoints/` |
| 2026-10-19 | 2 | CLAP `laion/larger_clap_music_and_speech` (~0.8 GB) | auto-download → `cache/huggingface/` |
| 2026-10-19 | 2 | audio-separator: `htdemucs` (~80 MB), BS-RoFormer ep317 (640 MB) | auto-download → `cache/audio-separator/` |
| 2026-10-19 | 3 | ctc-forced-aligner 0.3.0 (BSD-2, GitHub commit `64293cc`) + uroman 1.3.1.1 | `uv add "ctc-forced-aligner @ git+https://github.com/MahmoudAshraf97/ctc-forced-aligner.git"` |
| 2026-10-19 | 3 | MMS-300m forced-aligner model (CC BY-NC 4.0, 1.2 GB) | auto-download → `cache/huggingface/` |
| 2026-10-19 | 4 | scenedetect 0.7.2, mediapipe 1.1.1, imagehash 4.3.2, opencv-contrib-python 5.0.0.93 | `uv add scenedetect mediapipe imagehash opencv-contrib-python` (scenedetect still pulls `opencv-python`; contrib is reinstalled last: `uv sync --reinstall-package opencv-contrib-python`) |
| 2026-10-19 | 4 | YuNet face detector (opencv_zoo, MIT, 232 KB) | `https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx` → `cache/opencv/` (SHA-256 in `cache/opencv/SHA256`) |
| 2026-10-19 | 4 | MediaPipe BlazeFace short-range + EfficientDet-Lite0 (Apache-2.0) | `storage.googleapis.com/mediapipe-models/...` → `cache/mediapipe/` (SHA-256 in `cache/mediapipe/SHA256`) |
| 2026-10-19 | 4 | SigLIP 2 base patch16-224 (Apache-2.0, 1.5 GB) | auto-download → `cache/huggingface/` |
| 2026-10-19 | 6 | RIFE (TNTwise rife-ncnn-vulkan 20250112, 827 MB), Real-ESRGAN ncnn (xinntao v0.2.5.0, 45 MB), deep-filter 0.5.6 (27 MB) | official GitHub releases → `bin/` (see `bin/README.md`; SHA-256 recorded) |
| 2026-10-19 | 6 | auto-editor 29.3.1 | `uv add auto-editor` (its first run downloads the official release binary; SHA-256 matches GitHub's digest `ba8eecd6…`) |
| 2026-10-19 | 6 | HyperFrames remove-background model (u2net_human_seg) | auto-download on first `tools/hf.py remove-background` |
| 2026-10-19 | 3 | sentencepiece 0.2.2, openvino 2026.4.1, nncf 3.4.0 | `uv add sentencepiece openvino nncf` |
| 2026-10-19 | 3 | bodhan-ai/indic-transcribe-core @ e083ab7 (gated; Indic Open Model License v1.0), fp32 `model.safetensors` 4.89 GB + code/configs (the duplicate `.nemo` skipped) | `snapshot_download` after `hf auth login` → `cache/models/indic-transcribe-core/` |
| 2026-10-19 | 3 | bodhan-ai/indic-transcribe-flex @ ecba9ba (gated; same licence), fp32 4.89 GB — **the default model** | `snapshot_download` → `cache/models/indic-transcribe-flex/` |
| 2026-10-19 | 3 | Flex OpenVINO IR, int8 weights (1.24 GB) | `uv run tools/export_indic_ov.py --model flex` → `cache/models/indic-transcribe-flex-ov-int8/` |
| 2026-10-19 | 3 | num2words 0.5.14 (aligner: spoken form of digits) | `uv add num2words` |
| 2026-10-19 | 3 | OpenVINO IR, int8 weights (1.24 GB), built locally | `uv run tools/export_indic_ov.py` → `cache/models/indic-transcribe-core-ov-int8/` |
| 2026-10-19 | 3 | adidsh/indic-transcribe-core-int8-onnx (1.57 GB, SHA-256 verified) — **rejected** (43 % WER, not loadable by OpenVINO) | deleted 2026-10-19 with the user's OK (1.5 GB freed) |
| 2026-10-19 | 7 | kokoro-onnx 0.6.1 (+ phonemizer, espeakng-loader); Kokoro-82M model auto-downloaded by `hyperframes tts` on first use | `uv add kokoro-onnx` |
| 2026-10-19 | 5 | Antigravity CLI `agy` 1.4.2 → `%LOCALAPPDATA%\agy\bin\agy.exe` (on the user PATH; self-updating). Signed in already: it reuses the Antigravity app's Google login | official installer `https://antigravity.google/cli/install.ps1`, downloaded and **read first** (it verifies the binary's SHA-512 against Google's manifest), then run locally. Binary SHA-256 `4F6C7A80…2A7BE0` |
| 2026-10-19 | 3 | Parakeet TDT 0.6B v3 int8 (640 MB) + sherpa-onnx runtime | `uv run tools/hf.py models install parakeet` → `~/.cache/hyperframes/parakeet/` (C:) |

The Claude Code plugin route (`claude plugin install hyperframes@hyperframes`) was skipped: the skills are installed project-locally instead, which is all the studio needs.

## HyperFrames environment (set by `tools/hf.py`)

| Variable | Value | Why |
|---|---|---|
| `HYPERFRAMES_FFMPEG_PATH` / `HYPERFRAMES_FFPROBE_PATH` | Gyan full build | PATH order would pick the choco essentials build |
| `HYPERFRAMES_PYTHON` | `.venv\Scripts\python.exe` | the studio's Python |
| `HYPERFRAMES_NO_TELEMETRY` | `1` | no usage telemetry |
| `HYPERFRAMES_SKIP_SKILLS` | `1` | stops `init` from installing skills into every AI tool on the machine |
| `HYPERFRAMES_EXTRACT_CACHE_DIR` | `cache\hf-frames` | keeps the frame cache on D: |
| `HF_HOME` | `cache\huggingface` | model downloads on D: |
| `TORCH_HOME` | `cache\torch` | Beat This! weights on D: (HyperFrames looks for `small0` there) |
| `HYPERFRAMES_BEAT_THIS_PYTHON` | `.venv\Scripts\python.exe` | `hyperframes audio`/`beats` use Beat This! instead of the signal fallback |
| removed | `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `HEYGEN_*`, `ELEVENLABS_API_KEY`, `OPENROUTER_API_KEY`, … | some HyperFrames skills auto-use these paid or limited APIs (e.g. Lyria music generation via `GEMINI_API_KEY`) |

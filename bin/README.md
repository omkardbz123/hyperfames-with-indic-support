# bin/ — vendored binaries (git-ignored)

Only official GitHub release builds. Each folder has a `VERSION` (release, URL, licence) and a `SHA256`
(the downloaded archive and the executables). `uv run tools/doctor.py` re-hashes the executables and
fails on any mismatch. Download into `_dl/<tool>/` first, check the byte size against the release API,
then extract here.

| Folder | Release | Size | Used for |
|---|---|---|---|
| `rife/` | TNTwise/rife-ncnn-vulkan `20250112` → `windows.zip` (all RIFE models v2–v4.26) | 827 MB | frame interpolation / slow-mo (`tools/fx.py slowmo`) |
| `realesrgan/` | xinntao/Real-ESRGAN `v0.2.5.0` → `realesrgan-ncnn-vulkan-20220424-windows.zip` | 45 MB | upscaling (`tools/fx.py upscale`) |
| `deepfilter/` | Rikorose/DeepFilterNet `v0.5.6` → `deep-filter-0.5.6-x86_64-pc-windows-msvc.exe` | 27 MB | voice denoise (`tools/fx.py denoise-voice`) |

auto-editor is not here: its pip package downloads the official 29.3.1 release binary into
`.venv/Lib/site-packages/auto_editor/bin/` on first run; doctor checks it against the GitHub digest.

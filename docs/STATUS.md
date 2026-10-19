# Build status

Phase checklist for `docs/BUILD_PLAN.md`. Updated after every phase.

| Phase | Name | Status |
|---|---|---|
| 0 | Preflight and skeleton | ✅ passed (1 ⛔ USER item open: leaked `GEMINI_API_KEY`) |
| 1 | Rendering core (HyperFrames) | ✅ passed |
| 2 | Audio understanding | ✅ passed |
| 3 | Speech, lyrics, captions | ✅ passed (real Hindi clip skipped by user decision; lyrics on a real song moves to Phase 9) |
| 4 | Footage understanding | ✅ passed |
| 5 | Perception via Antigravity | ✅ passed (no separate sign-in was needed) |
| 6 | Footage processing toolkit | ✅ passed |
| 7 | Voice, text, fonts | ✅ passed (translation via `agy` lands with Phase 5) |
| 8 | Asset sourcing and library | ✅ passed with free providers (Pexels/Pixabay wait on ⛔ USER keys) |
| 9 | Planning and build layer | ✅ passed |
| 10 | Review and QA | ✅ passed |
| 11 | Export | ✅ passed |
| 12 | Commands, skills, memory | ✅ passed |
| 13 | End-to-end demos | ✅ 3 demos built, reviewed, exported (demo 2 = draft until facts confirmed; demo 3 = private draft, source licence unknown) |

## Open ⛔ USER items

1. ~~Revoke the leaked Gemini API key~~: **revoked by the user (2026-10-19).** If `GEMINI_API_KEY` is still listed under Environment Variables → User variables, delete it too so `tools/doctor.py` stops warning.
2. **GoaALM facts** (export of GoaALM videos is blocked until confirmed): the exact December 2026 date (day), the handle @goaalm, the Marathi/Hindi names ("गोवा प्राणी मुक्ती मोर्चा" / "गोवा पशु मुक्ति मार्च"), the Marathi/Hindi end-card wording (`end_card_mr` / `end_card_hi` in `library/brands/goaalm/brand.json`), and a logo file (PNG/SVG with transparency) if there is one.
3. **The Marathi VO script of demo 2** (`projects/demo-marathi-promo/vo_script.json`) was written by Claude: check the wording.
4. **Licences of `inbox/hindi.mp4` and `inbox/marathi.mp4`.** hindi.mp4 carries an Indian Express Hindi watermark (third-party news footage): fine for private tests, **not for posting**. If you shot marathi.mp4 yourself, say so and it gets an "own footage" licence.
5. **Optional:** free Pexels + Pixabay API keys (pexels.com/api, pixabay.com/api/docs) as user environment variables `PEXELS_API_KEY` / `PIXABAY_API_KEY`: more and better stock video. Until then: Openverse + Wikimedia Commons.
6. **Optional:** skim `inbox/marathi.transcript.txt` and `inbox/hindi.transcript.txt`.
7. **Optional, disk space (needs your OK):** the unused Indic-Transcribe-Core models (`cache/models/indic-transcribe-core` 4.6 GB, `…-core-ov-int8` 1.2 GB), the `_dl/` downloads (~0.9 GB) and `_trash/` can be deleted.

---

## Phase 0: Preflight and skeleton ✅

- Versions recorded in `docs/ENVIRONMENT.md`.
- Folder layout created; `git init` on `main`; `.gitignore`, `.env.example` (names only), `bin/README.md`, `.python-version`.
- `.venv` (Python 3.11.6, uv) with the base packages; `pyproject.toml` + `uv.lock`.
- `config/studio.toml` pins absolute FFmpeg/ffprobe (Gyan 8.0.1 full) and Chrome paths; `config/export_presets.toml` holds §12.
- `package.json` written by hand as `ai-video-studio` (ENOSELF avoided).
- **Accept:** `uv run python -c "import librosa, cv2"` ✅; `uv run tools/doctor.py` all green for phases 0–1, except the ⛔ USER key warning.

**Plan corrections**
- §3 says two FFmpeg builds are on PATH; there are **four** (choco essentials, `C:\ffmpeg` essentials, yt-dlp's build, Gyan full). The full build is pinned.
- The `py` launcher's default is Python 3.14.2, not 3.11; irrelevant because the studio uses uv's `.venv`.

## Phase 1: Rendering core ✅

- HyperFrames CLI **0.8.172** pinned in `package.json`; `hyperframes doctor` ✅ (whisper-cpp / Kokoro / MusicGen are optional and come in later phases).
- 21 HyperFrames skills installed project-locally in `.claude/skills/`.
- `hyperframes browser ensure` → chrome-headless-shell 152.
- **`tools/hf.py` wrapper**: pins FFmpeg via `HYPERFRAMES_FFMPEG_PATH`/`HYPERFRAMES_FFPROBE_PATH` (HyperFrames otherwise picks the choco essentials build), disables telemetry, keeps caches on D:, and strips cloud API keys. Some skills (`media-use`) silently use `GEMINI_API_KEY` for Lyria music, HeyGen and ElevenLabs.
- Test renders: `kinetic-type` example at 1080×1920 (15 s, 49 s render) and `warm-grain` at 1920×1080 (10 s, 18 s render). Both are H.264 High yuv420p 30 fps and play correctly (contact sheets checked).
- Catalog: 447 items (210 blocks, 237 components) → `docs/CATALOG_NOTES.md`, regenerated with `uv run tools/catalog_notes.py`. Every item the plan names exists: `glitch`, `cinematic-zoom`, `whip-pan`, `flash-through-white`, `light-leak`, `chromatic-radial-split`, `beat-freeze-cut`, `caption-pill-karaoke`, `caption-kinetic-slam`, `caption-highlight`, `caption-editorial-emphasis`, `caption-glitch-rgb`, `caption-neon-glow`, 13 lower thirds, light-leak overlays.
- **Devanagari render test** (`projects/_test-devanagari`): `क्ष त्र ज्ञ श्र द्ध ळ ऱ्या मराठी हिंदी` in 9 fonts, snapshot inspected.
  - ✅ Conjuncts correct: Noto Sans Devanagari, Mukta, Tiro Devanagari Marathi, Baloo 2, Rozha One (traditional ज्ञ form), Kalam, Hind.
  - ❌ **Yatra One** has no conjunct support (renders क्‌ष, त्‌र, ज्‌ञ with visible halants). Use it only for conjunct-free words.
- Fonts: 17 OFL families from google/fonts → `library/fonts/` (`uv run tools/fetch_fonts.py`; licence index in `library/fonts/index.json`).
- Benchmark: see below.

**Plan corrections**
- Local fonts must ship inside each project (`assets/fonts/` + an in-file `@font-face`). The render browser is a clean headless shell with no system fonts, and `lint` enforces this (`font_family_without_font_face`).
- `init` checks/installs skills for every AI tool by default; the wrapper sets `HYPERFRAMES_SKIP_SKILLS=1` because skills are managed with `npx skills` in `.claude/skills/`.

### Render speed (Phase 1 benchmark)

`hyperframes benchmark --runs 1` on the `kinetic-type` example (15 s, 1080×1920, 450 frames, with a video layer). Single runs are noisy, and the benchmark's own renders fell back to software GL (SwiftShader):

| Config | Time | Size |
|---|---|---|
| 30 fps · draft · 2 workers | 40.5 s | 5.8 MB |
| 30 fps · standard · 2 workers | 76.8 s | 7.6 MB |
| 30 fps · high · 2 workers | 54.3 s | 12.0 MB |
| 30 fps · standard · 4 workers | 41.3 s | 7.6 MB |
| 60 fps · standard · 4 workers | 83.4 s | 8.1 MB |

Own A/B with normal `render` (hardware-GPU capture, default `looks` quality):

| Workers | `HF_CAPTURE_PARALLEL_STREAM` | Render time |
|---|---|---|
| 4 | false | 41.0 s |
| 6 | false | 39.6 s |
| 8 | false | 79.8 s (outlier: 52 s compile) |
| **6** | **true** | **32.3 s** ← chosen |
| 8 | true | 33.8 s |

- **Chosen:** 6 workers + parallel stream (`[render]` in `config/studio.toml`; `tools/hf.py` applies both). That's about **2.2 s of render per second of 1080×1920 video** for this composition.
- Every render has a fixed ~10 s "compile" step, even for a static 5 s card (the Devanagari card took 20.4 s in total). Short tests therefore look slower per second than long renders.

**Accept:** test renders play ✅ · Devanagari snapshot **and MP4 frame** correct ✅ · render speed recorded ✅

## Phase 2: Audio understanding ✅

**Tools:** `tools/analyze_audio.py` (→ `analysis/<id>/audio.json` + `audio.png`), `tools/separate.py` (stems), `tools/audiolib.py` (decode/levels/SFX/loudness, ported from the Goa `audio.py`), `tools/assets.py` (asset IDs), `tools/make_fixtures.py` (synthetic test media with exact ground truth), `tests/eval_audio.py` and `tests/eval_stems.py` (scorers). Schema: `docs/CONTRACTS.md`.

### Acceptance

**BPM within ±1 of the reference** ✅ on four tracks:

| Track | Reference | Measured | HyperFrames cross-check |
|---|---|---|---|
| `beat_128.wav` (synthetic) | 128 | **127.98** | 114.6 with its Beat This! `small0` (see below) |
| Go Cart – Drop Mix (Kevin MacLeod, CC BY 4.0) | 115 | **115.0** | 115.1 |
| Club Diver (Kevin MacLeod, CC BY 4.0) | 140 | **140.0** | 139.9 |
| B-Roll, 1:24 version (Kevin MacLeod, CC BY 4.0) | 89 | **89.99** | 90 |

The incompetech catalogue lists two "B-Roll" versions (123 BPM / 1:01 and 89 BPM / 1:24); the downloaded file is the 1:24 one.

**Ground-truth fixture** (`uv run tests/eval_audio.py`, all 10 checks pass):

| Check | Result |
|---|---|
| beats F (±70 ms) | 0.994, mean error **4.6 ms** |
| downbeats F | 1.000 |
| kick / snare / hi-hat F (±30 ms) | 0.97 / 1.00 / 0.92, timing error 3–8 ms |
| drop | 22.997 s (truth 23.0) |
| hard-stop edges | 21.084 / 22.996 s (truth 21.078 / 23.0) |
| beat grid reliable | true |

**Beat PNG looks right** ✅. Checked Go Cart (breakdown 68.9–75.7 s, drop on the first kick of the re-entry at **76.196 s**) and Club Diver (16-bar phrase boundaries at 30.9 / 58.3 / 85.8 / 113.2 s, each 27.4 s = 16 bars at 140 BPM).

**CLAP tags plausible** ✅ (`laion/larger_clap_music_and_speech`):
- Go Cart: aggressive phonk 0.80, EDM drop 0.11, dark electronic 0.03
- Club Diver: aggressive phonk 0.70, synthwave retro 0.10, dark electronic 0.09
- B-Roll (a jaunty band piece): comedy quirky 0.76, rock 0.13, uplifting corporate 0.05

**Stems separate audibly** ✅ (`uv run tests/eval_stems.py`, a 40 s fixture of an edge-tts Marathi voice over the drum track, with known parts):

| Model | Vocals SDR | Instrumental SDR | Vocal-band leakage | Speed (CPU, 16 threads) |
|---|---|---|---|---|
| **htdemucs** (default) | 28.1 dB | 26.8 dB | −67 dB | **0.92× real time** (0.54× on a 131 s track) |
| htdemucs_ft | 27.9 dB | 24.9 dB | −69 dB | 3.1× |
| **BS-RoFormer ep317** (`--quality`), overlap 2 | **32.2 dB** | **35.4 dB** | −98 dB | 7.8× |
| BS-RoFormer ep317, model default overlap 4 | 32.2 dB | 35.4 dB | −98 dB | 16.7× |
| Kim_Vocal_2 (MDX, ONNX) | 6.6 dB ❌ | 10.0 dB | −63 dB | 1.0× |

### Measured speed

- Full analysis with tags and the cross-check (warm cache): **28–35 s per 1.5–2.5-minute track** (about 0.25× real time). The breakdown for a 131 s track: Beat This! 6.7 s, onsets/energy 2.8 s, sections 0.6 s, CLAP 10.4 s, `hyperframes audio` 10.5 s.
- First run only: CLAP model load and download (~0.8 GB) added about 90 s.
- Stems: htdemucs about 0.5–0.9× real time; RoFormer about 8× real time (a 3-minute song takes ~25 min, so use it only for lyrics).

### Workarounds and plan corrections

- **DirectML doesn't help stems.** audio-separator runs RoFormer (MDXC) and Demucs on CPU even with `[dml]`; only MDX `.onnx` models use DirectML, and the best of those scored 6.6 dB on vocals. Kept the `[cpu]` extra; PyTorch XPU (Intel Arc) is to be evaluated in Phase 3.
- **`/music-to-video`'s `analyze-beatgrid.py` is less accurate than `audio.json`.** It read Go Cart as 57.4 BPM (half tempo) and reports silences and key moments to the second. `audio.json` is the timing source of truth; a Phase 9 adapter will rewrite the skill's `audiomap.json` tempo/grid from it.
- **HyperFrames `audio`:** setting `HYPERFRAMES_BEAT_THIS_PYTHON` plus `TORCH_HOME` makes it use Beat This! (`small0`). That matches on real tracks but read the synthetic fixture as 114.6 BPM, so it is informational only. Its default provider ladder includes a cloud `api`, so the studio always passes `--quality local`.
- Beat This! reports beats on a 20 ms grid; a median-interval tempo read 128 BPM as 130.4. Tempo now comes from a least-squares fit over steady runs, and beats snap to the nearest precise onset (±35 ms).
- Kick/snare/hi-hat come from per-band level jumps with level gates, a fast body decay for snares, and per-drum minimum spacing. They are exact on the fixture, but on real mixes they are heuristics (Go Cart: 382 kicks at a median half-beat spacing). `--stems` uses the Demucs drums stem for cleaner results.
- Test media: three Kevin MacLeod tracks (CC BY 4.0) in `library/music/incompetech/`, git-ignored. The server was fast, not slow. They'll be indexed with licence and credit in Phase 8.

## Phase 3: Speech, lyrics and captions 🟡 (local parts done)

**Tools:** `tools/transcribe.py` (routes: script/lyrics alignment, English ASR, Marathi/Hindi ASR), `tools/align.py` (MMS forced aligner), `tools/captions.py` (cue pages, SRT/VTT, HyperFrames transcript). Fixtures: `speech_<lang>_<f|m>` (natural sentences) and `words_<lang>` (words joined with known gaps, so timings are exact). Scorers: `tests/eval_align.py`, `tests/eval_caption_sync.py`, `tests/make_caption_test.py`. Schema: `docs/CONTRACTS.md`.

### Results so far

**Forced alignment (MMS-300m)** on exact-timing fixtures, `uv run tests/eval_align.py`:

| Fixture | Words | Median start error | 90th pct | Starts within 80 ms |
|---|---|---|---|---|
| words_mr | 18 | 14 ms | 57 ms | **100 %** |
| words_hi | 26 | 37 ms | 67 ms | **100 %** |
| words_en | 25 | 43 ms | 61 ms | **100 %** |

On connected speech (`speech_*`), checked at the exact boundaries (sentence start and after the mid-clip pause), errors run −75 to +40 ms.

**English ASR (Parakeet TDT 0.6B v3)**: WER 8 % on both English clips. The only errors were "Panaji" → "Punji" and "cows" → "cow". Its own timings: median start error 35 ms, 91 % within 80 ms. They sit on a 40–80 ms grid with words butted together, so `transcribe.py` re-times them with MMS by default.

**Caption render** (`projects/_test-captions`: 9:16, Mukta, the pill-karaoke logic driven by aligned Marathi words), `uv run tests/eval_caption_sync.py` ✅:
- highlight vs word time in the MP4: +3…+30 ms (within one frame at 30 fps)
- audio placement in the MP4: **0.0 ms** offset (cross-correlation with the source)
- highlight vs actual voice onset: median +20 ms, max 55 ms, **100 % within ±80 ms** (target ±80 ms)
- frames inspected: word-by-word highlight progresses, and Devanagari conjuncts shape correctly.

**Speed:** MMS alignment ~1.5 s per 11–18 s clip (RTF ≈ 0.1) once loaded, plus ~15 s one-time model load per process. Parakeet ~4 s per 11.5 s clip (RTF ≈ 0.35, startup included).

### Still to do (needs ⛔ USER)

- Indic-Transcribe-core for Marathi/Hindi: model card API, CPU vs XPU speed (RTF), flex / SraVaani / IndicConformer fallbacks.
- Acceptance 1: edge-tts mr/hi round-trip WER < 10 % (fixtures `speech_mr_*`, `speech_hi_*` are ready).
- Acceptance 2: your real Marathi and Hindi clips.
- Lyrics mode on a real song (vocal stem, then alignment).

### Findings and plan corrections

- **edge-tts WordBoundary timings are not ground truth.** The first word is always reported at 0.100 s while the voice starts at 0.16–0.21 s, with ±100 ms scatter after that. They're fine for scripting voiceovers, but timing tests use the `words_*` fixtures. In Phase 7, caption timing for TTS voiceovers should come from MMS alignment of the generated audio.
- **ctc-forced-aligner's two modes err in opposite directions.** With a `<star>` filler only at the edges, starts land ~95 ms early (the preceding silence is absorbed); with a star per word, starts are +25–45 ms but ends scatter ±130 ms. `align.py` uses per-word stars for starts, edge stars for ends, and the measured bias corrections in `[align]` (`config/studio.toml`).
- HyperFrames' `caption-pill-karaoke` highlights words 50 ms early by design (`WORD_FADE_LEAD`) and loads Poppins from Google Fonts. The studio's version uses a 0 ms lead and a local Mukta.
- HyperFrames keeps Parakeet in `~/.cache/hyperframes/` on C: (640 MB); no setting to move it was found.

## Phase 4: Footage understanding ✅

**Tools:** `tools/analyze_video.py` (video.json, thumbs, contact sheet), `tools/siglip.py` + `tools/index_footage.py` + `tools/search_footage.py` (text search), `tools/track_subject.py` (auto-reframe), `tools/analyze_photos.py`. Scorers: `tests/eval_shots.py`, `tests/eval_search.py`, `tests/eval_reframe.py`, `tests/eval_photos.py`. Schemas: `docs/CONTRACTS.md`.

**Test footage:** Tears of Steel 1:00–3:00 (Blender Foundation, CC BY 3.0) in `tests/fixtures/footage/` with a licence sidecar. Its 19 cuts were verified by eye: before/after frame pairs for every cut, plus 2 fps strips of every shot longer than 10 s to look for missed cuts. A suspected cut at 104.8 s turned out to be a camera move (no frame-difference spike).

### Acceptance

**Shot cuts within ±2 frames** ✅ (`uv run tests/eval_shots.py`):
- real excerpt: 19/19 cuts, none extra, **0 frames** from the frame-difference spike on every cut
- montage with exact truth (14 frame-exact segments): 12/12 hard cuts, none extra, **0 frames** error; the fade through black is found 1 frame from its midpoint and labelled `fade`

**Search returns relevant shots** ✅ (`uv run tests/eval_search.py`): 9 queries, **hit@1 9/9** ("a man aiming a sniper rifle", "aerial view of an old city with church towers", "a huge church organ in a gothic hall", "a flying ship seen through a rifle scope", …).

**Reframe follows a face smoothly** ✅ (`uv run tests/eval_reframe.py`, 36 s of face shots → 9:16):
- 100 % of face samples fully inside the crop and in its middle 70 % (290 of 291 strictly inside)
- jitter 0 px/frame²; 1 wobble in 16 s of panning; 8 large reversals that follow the subject; peak pan 0.36 frame widths/s
- review strip checked (`_previews/reframe_916_sheet.jpg`)

**Photos** ✅ (`uv run tests/eval_photos.py`, generated with exact truth): EXIF orientation 6 comes out upright; only the blurred copy is flagged (sharpness 3 vs 111–261); all 3 duplicate pairs found with the originals kept; faces + face focus points; 1920×800 frames flagged as needing upscaling for 9:16.

### Speed (2-minute 1920×800 clip, CPU)

| Step | Time |
|---|---|
| analyze_video (shots, 4 fps metrics, faces, sheet) | 20–26 s (~0.2× real time) |
| SigLIP index (140 frames) | 35 s warm (first run downloads 1.5 GB) |
| search | ~0.2 s per query once loaded (~1.7 s incl. model load) |
| track_subject (36 s span, 10 fps) | 9 s |

### Workarounds and plan corrections

- **MediaPipe 1.1 dropped the legacy `solutions` API**, so the Tasks API with official `.tflite` files is used. **BlazeFace short-range missed medium-distance faces** (0 % on a two-shot with two clear faces), so faces come from **YuNet** (OpenCV zoo), with BlazeFace as a fallback.
- **OpenCV:** MediaPipe needs `opencv-contrib-python`, but PySceneDetect hard-depends on `opencv-python`. Both are 5.0.0.93, and contrib is installed last (`uv sync --reinstall-package opencv-contrib-python` if `cv2.saliency` ever goes missing; the doctor checks for it).
- **Reframe:** detectors drop out for a few frames on dark or turned faces. Falling back to saliency swung the crop away and back (91 % containment), so gaps ≤ 1.5 s inside a shot are bridged from neighbouring face samples. Savitzky-Golay smoothing overshot (24 direction reversals per 10 s); a Gaussian (0.25 s) plus 2 px hysteresis fixed it.
- **Downloads:** ffmpeg's HTTP reader against Wikimedia triggered a 429 (too many range requests). Backed off and used the Xiph.org mirror the Commons page credits as the source, with a single curl range request. Rule: fetch media with one curl request, then let ffmpeg read the local file.
- PySceneDetect's AdaptiveDetector doesn't see fades; ThresholdDetector (same decode pass) catches fades through black. Cross-dissolves aren't detected as boundaries yet (not needed for the acceptance tests; revisit if a recipe needs them).

## Phase 6: Footage processing toolkit ✅

**Tools:** `tools/fx.py` (slowmo, upscale, stabilize, cut-silence, denoise-voice, speed, lut, key, denoise-video, deinterlace, trim, timecode) and `tools/make_luts.py`. Binaries in `bin/` (official releases, sizes verified against the GitHub API, SHA-256 recorded and re-checked by the doctor). Scorers: `tests/eval_slowmo.py`, `tests/eval_stabilize.py`, `tests/eval_audio_fx.py`, `tests/smoke_fx.py`.

**GPU path:** RIFE and Real-ESRGAN (ncnn + Vulkan) both run on the **Intel Arc** (device 0, fp16). Everything else is CPU.

### Acceptance

**2 s clip → 4× slow-mo without obvious artefacts** ✅. Hold-out test (`uv run tests/eval_slowmo.py`): 48 real frames at 960 px, every 4th kept, 33 rebuilt and compared with the real ones:

| Method | PSNR | SSIM | Worst frame SSIM | Time |
|---|---|---|---|---|
| plain slow-down (duplicate frames) | 19.7 dB | 0.559 | 0.505 | — |
| ffmpeg minterpolate | 27.6 dB | 0.837 | 0.684 | 4.1 s |
| **RIFE v4.6** (default) | **33.3 dB** | **0.955** | **0.913** | 3.7 s |
| RIFE v4.22 | 33.2 dB | 0.945 | 0.893 | 5.1 s |
| RIFE v4.26 | 33.6 dB | 0.950 | 0.892 | 4.4 s |

The generated frame was inspected next to the real one (`_previews/slowmo_compare.jpg`): no ghosting or warping.

**480p → 1080p upscale works** ✅. A real frame was shrunk to 854×356 and brought back to 1920×800. realesrgan-x4plus restores crisp line detail (sharpness 85 vs lanczos 9; the original is 29, a soft cinema frame); lanczos scores highest PSNR because it invents nothing. Video path (frames → GPU → re-mux with audio) verified on a 2 s clip: **animevideov3 21 s, x4plus 642 s** for 48 frames.

**Shaky clip stabilises** ✅ (`uv run tests/eval_stabilize.py`): a known synthetic handheld shake on a locked-off shot. Mean frame-to-frame motion went from **20.7 px to 0.26 px** (the steady original measures 0.18 px), in 7.5 s for 4 s of 1080p.

**Silence cutting works** ✅ (`uv run tests/eval_audio_fx.py`): speech clips with 5.3 s of inserted pauses (14.7 s of quiet in total) went from 38.4 s to 28.5 s, with **99.8 % of voiced time kept**, in 1.9 s.

**Voice denoise** ✅ (same test): speech plus white noise and 50 Hz hum at 5 dB SNR. SI-SDR −1.3 → 8.2 dB (+9.5); **noise floor between words −22.8 → −59.1 dB**; 7× faster than real time. For comparison, ffmpeg `afftdn` gave −1 dB SI-SDR and a 1.2 dB lower floor.

**Smoke tests** ✅ (`uv run tests/smoke_fx.py`): speed ×2, frame-accurate trim, hqdn3d, bwdif, timecode burn-in, chroma key → ProRes 4444 (yuva444p12le) and → WebM VP9 alpha, and HyperFrames `remove-background` on a photo (RGBA, 26 s including the first model download). Looks: 5 own-made `.cube` LUTs, checked in a preview grid and through ffmpeg `lut3d`.

### Workarounds and plan corrections

- **rife-ncnn-vulkan `-n` timing:** output j is placed at input time j·N/n, not j·(N−1)/(n−1). Asking for (N−1)·k+1 frames made every frame drift late, and RIFE scored barely above duplication (21 dB). `fx.slowmo` now requests N·k frames (exact 1/k steps) and drops the k−1 frames past the last input.
- **DeepFilterNet leaves mains hum** (50 Hz residual at −42 dB). An 80 Hz high-pass in front (default; `--highpass 0` disables it for deep voices) brings the floor to −59 dB.
- **The DeepFilterNet pip package** pins old torch/torchaudio APIs, so the plan's other option, the official standalone `deep-filter` binary, is used instead.
- **auto-editor's pip package is a launcher** that downloads the official release binary on first run. That's acceptable under §2.6 because the hash matches GitHub's published digest, and the doctor re-checks it.
- **Real-ESRGAN x4plus is too slow for video** (~13 s per 1080p frame on the Arc). Video defaults to realesr-animevideov3; x4plus stays the default for photos.
- **Background removal** keeps some bright non-person objects (balusters next to the subject) as partial foreground. Review cutouts; use chroma key when there's a real green screen.

### Phase 3, part 2: Marathi / Hindi ASR (after the Hugging Face login)

**What runs:** `tools/indic_asr.py` = bodhan-ai/indic-transcribe-core converted by `tools/export_indic_ov.py` to **OpenVINO IR with NNCF int8 weight-only compression** (1.24 GB, from the 4.89 GB fp32 checkpoint). It is split into three graphs: encoder, cross-attention K/V (computed once per clip), and a **cached** decoder step. The audio front-end, 10-token prompt and long-audio chunking/loop guard are ported from the official code (reviewed first: no network, shell, eval or pickle). `tools/transcribe.py --lang mr|hi` = this + MMS word timings + caption cues.

**Choosing the version** (you asked for OpenVINO + quantisation if possible):
- No OpenVINO build exists on Hugging Face. The community `adidsh/indic-transcribe-core-int8-onnx` (W8A8 dynamic) was downloaded and SHA-256 verified, but scored **43 % WER** on our fixtures (word loops: "गोव्यातील गोव्यातील गोव्यातील…"), and OpenVINO cannot load it (a dynamic-rank `If` op). Rejected.
- So the official fp32 checkpoint was downloaded (your fallback) and converted ourselves. The export checks parity against the upstream PyTorch model before converting: encoder max difference 0, logits ≤ 1.1e-5.

**Acceptance 1, edge-tts round trip (WER < 10 %)** ✅ (`uv run tests/eval_indic_asr.py --sets speech,words`):

| Version | mr+hi mean WER | Per clip (en_f, en_m, hi_f, hi_m, mr_f, mr_m) | Speed per ~11 s clip |
|---|---|---|---|
| official fp32 PyTorch (`--device official`) | **1.4 %** | 4.0, 4.0, 0, 0, 5.6, 0 % | ~3.0 s |
| **OpenVINO int8, CPU** (default) | **1.4 %** (identical text) | 4.0, 4.0, 0, 0, 5.6, 0 % | **~2.0 s** (RTF ≈ 0.17) |
| OpenVINO int8, Arc GPU | 1.4 % (identical text) | same | 4–7 s (dynamic shapes; slower than CPU here) |
| community int8 ONNX (rejected) | 43.4 % | 120, 84, 54, 31, 61, 28 % | ~3.7 s |

The only remaining errors are "Panaji" spelled "Panji"/"पंजी" and गायींना as गाईंना (a common variant).

**Acceptance 2, real speech:** your Marathi clip (`inbox/marathi.mp4`, 2:55, a street conversation) → 494 words, 140 caption cues, 7 chunks cut at pauses, **93 s in total** (ASR 51 s + alignment 45 s; RTF 0.55). The transcript reads coherently; `inbox/marathi.transcript.txt` is there for you to check. The Hindi clip is still to come.

**Acceptance 3, caption sync** ✅ (earlier: max 55 ms, 100 % within ±80 ms).

**Low-confidence flags:** recalibrated on real speech. The MMS alignment confidence has median 0.52 and 5th percentile 0.035 on the Marathi clip, so the threshold went from 0.3 (flagged 26 % of words) to **0.05** (27 of 494 words, mostly fast fillers like नाही/आहे).

**Accepted workaround (2026-10-19, user decision):** the real-Hindi-clip check is skipped. Hindi shares the model, front-end and pipeline with Marathi, scores 0 % WER on both Hindi fixtures, and is the model's stronger language on its own benchmark (3.5 % vs 5.7 % WER). Re-test when a Hindi video is made (Phase 13 demo 3 is a Hindi talking-head reel). Hinglish note: `--mode mixed` keeps English words in Latin script.

**Moved:** lyrics mode on a real song (vocal stem → alignment), which comes with the lyric-video recipe in Phase 9. LID (automatic language detection) isn't ported: the studio always passes the language, which the model card recommends anyway (its Hindi LID top-1 is only 0.26).

### Phase 3, part 3: Indic-Transcribe-Flex (English words in Latin script)

The user asked for English words to stay in Latin script. **Core ignores its mode switch** (its own help text: "this checkpoint produces native script"; verified with the official code: native, mixed and romanised all gave the same Devanagari text). **Flex** is the sibling trained for it. Flex was downloaded (4.89 GB, same architecture code; only its tokenizer/feature files and language-detection helpers differ, all reviewed) and exported the same way (parity: encoder identical, logits ≤ 1.7e-5).

| Model / version | mr+hi WER, native mode | Speed per ~11 s clip |
|---|---|---|
| Core, OpenVINO int8 | 1.4 % | ~2.0 s |
| Flex, official fp32 | **0.0 %** | ~3.2 s |
| **Flex, OpenVINO int8** (default) | **0.0 %** (identical text to fp32) | **~1.7 s** |

**Mixed mode** (`--mode mixed`): "**Goa** में पशु मुक्ति **March** इस रविवार पणजी में होगा", Marathi "**Goa**-तील … **Panaji**-त". The higher WER figures in mixed mode only reflect the script change against an all-Devanagari reference text. On the user's Hindi clip (2:04): 389 words, 74 of them in Latin ("protest", "scooty", "petrol pump", "E20", "I don't know what it is", "detain", "Ma'am"), 102 cues, 70 s. Proper names also come out in Latin ("Aditya Rana Adani जी"). Saved as `inbox/hindi.transcript.txt`.

**Aligner:** digits are now handled: Latin words with digits are aligned as their spoken English form ("E20" → "etwenty"), and pure numbers in mr/hi speech as a wildcard flagged for review. The exact-timing tests still pass at 100 %.

Defaults: `[indic_asr] model_native = model_mixed = "flex"`. Core (fp32 4.6 GB + int8 1.2 GB) is now unused and can be deleted with the user's OK.

## Phase 7: Voice, text and fonts ✅

**Tools:** `tools/voiceover.py` (ported from the Goa `voiceover.py`), `tools/caption_comp.py` (caption sub-composition generator, reused by the Phase 9 build), `tests/make_vo_test.py`.

- **edge-tts** (7.3.1, working): mr-IN Aarohi/Manohar, hi-IN Swara/Madhur, en-IN Neerja/Prabhat. Lines are trimmed (the ~1 s tail edge-tts adds is cut), and **word timings come from MMS alignment of the generated audio**, because WordBoundary is off by up to ~100 ms (Phase 3 finding). Lines are cached by text, voice, rate and pitch.
- **Kokoro-82M** (offline, through `hyperframes tts`, after `uv add kokoro-onnx`): English and **Hindi** (`hf_alpha`) both round-trip through ASR word for word. It has no Marathi voice, so edge-tts stays primary for Marathi.
- **Fonts:** the 17 families from Phase 1. Caption default is Mukta ExtraBold (Devanagari + Latin in one family).
- **Translation and scriptwriting via `agy`:** text-only presets in `tools/perceive.py` (Phase 5). They need the `agy` sign-in.

**Acceptance: a Marathi voice line + Devanagari kinetic caption render in sync** ✅ (`projects/_test-vo`: 3 Marathi lines, 2 voices, 20 words, kinetic style):
- highlight vs word time in the MP4: +0…+32 ms (within one frame)
- audio placement: 0.0 ms
- highlight vs voice onset: median +25 ms, **max 32 ms, 100 % within ±80 ms**
- snapshot checked: centred inside the safe zone, current word in the accent colour, conjuncts correct; HyperFrames lint 0 errors / 0 warnings.

**Fixes found along the way:** the caption host slot needs `class="clip"` (otherwise the layer had no size and the captions drifted left) and `data-track-kind="captions"` (lint).

## Phase 5: Perception through Antigravity ✅

**Install:** `agy` 1.4.2 via Google's official installer (read before running; it checks the binary's SHA-512). **It reuses the Antigravity app's login, so no separate sign-in was needed.** `agy models` lists `gemini-3.8-flash-high` (the effort is part of the slug); that's in `[gemini]` of `config/studio.toml`.

**Tool:** `tools/perceive.py`, with 8 media presets, 3 text presets (translate / script / highlights), proxies, a sandboxed job folder (`perception/<job>/` holds only proxies + TASK.md + schema.json), headless agy with `--json-schema`, automatic canaries, retry, cache (`analysis/<id>/gemini/`), and the manual relay (`--relay` / `--ingest`). It never uses `--dangerously-skip-permissions`; agy's attempts to run shell commands are soft-denied, as intended.

### What was learned (measured)

1. **Files must be attached as `@file` in the prompt.** A plain path ("open ./proxy.mp4") made the agent try a shell command (denied), and the log showed `media=0`.
2. **Video is fully watched** (about 1 frame/s) and the soundtrack fully heard. A first test suggested "only ~7 frames"; that was **my fixture's fault**: its video stream was only 7 s long under 20 s of audio, and Gemini correctly reported "no video frames visible" for the rest. The canaries surfaced the anomaly.
3. **In a bare audio file Gemini's sense of time is compressed** (it called a 40 s excerpt "31 s"; drop at "0:15" vs the real 0:21). Fix: audio-only assets are sent as **a running-clock video + the audio**. Then its build-up (1:09) and drop (1:17) matched our local analysis (1:08.9 / 1:16.2).
4. **It misses quiet background music under a loud voice** (once; another run caught it). Use `music_feel` on the music itself.
5. **Speed/cost:** a 20 s clip takes 1–2 min (35–50k tokens, mostly thinking). A 40 s audio-feel job takes about 2 min. A translation takes about 2 min.

### Acceptance

**Test #1** (20 s clip with known speech, on-screen text, music and a cut; `tests/fixtures/perception/known20.mp4` + `.truth.json`) ✅ on the first attempt:
- timecode range 00:00 → 00:19/20 ✅
- the hard cut at 12 s (our shot detection: 12.29 s) ✅
- first words "The Goa Animal Liberation March" ✅ (checked against our transcript)
- on-screen text "GOA ANIMAL MARCH 26 OCT" ✅, both scenes described correctly ✅, the music described ✅

**A bad canary is detected and rejected** ✅ (offline): simulated answers that "only watched 7 s", invented cuts, missed the cut, or gave wrong first words all fail; the real answer passes. The audio-duration canary caught a real compressed timeline live. The out-of-span check caught a fabricated "energy arc" up to 1:21 for a 40 s excerpt.

**Fallback works end to end** ✅: `--relay` writes `RELAY.md` (files, prompt, schema), and `--ingest` validates the pasted answer with the same canaries and caches it.

**Text tasks** ✅: an English → Marathi translation came back natural and correct ("प्राण्यांनाही आपल्यासारख्याच वेदना होतात." / "सकाळी ९ वाजता").

### Rules that follow
- Gemini timestamps are approximate. Never cut on them; snap to `audio.json` / `video.json` / `transcript.json`.
- Quota is shared with the Antigravity app. Cache everything, and batch questions into one call per asset.

## Phase 8: Asset sourcing and library ✅ (free providers)

**Tools:** `tools/stock.py`, `tools/music_library.py`, `tools/sfx.py`, `tools/brand.py`, `tools/credits.py`.

- **Stock search** over Pexels, Pixabay (keys ⛔ USER), Openverse (no key; photos + audio) and Wikimedia Commons (no key; photos + videos). Only CC0 / PD / CC BY / CC BY-SA (plus the Pexels/Pixabay licences) pass. API answers are cached 24 h; Commons downloads are paced ≥ 4 s and `Retry-After` is honoured (the Goa lessons). Photos are saved EXIF-upright with a `.license.json` sidecar. **Test:** "cow india street" → 16 results; Commons gave relevant, high-resolution photos, including portrait 2304×3072 and 4000×6000 (9:16-friendly). An audio search for "dhol drum india" found two **CC0 "Dhol Tasha Maharashtra"** recordings.
- **Music library:** 5 tracks indexed (3 Kevin MacLeod CC BY 4.0 + 2 CC0 dhol), each with BPM, key, loudness, CLAP tags, sections, drops, an energy profile and a credit line. Mood search with CLAP embeddings ranks correctly: "festive Indian drums" → the dhol tracks; "aggressive phonk" → Go Cart, Club Diver; "cheerful comedy" → B-Roll.
- **SFX:** 15 synthesised effects (boom, thud, riser, whoosh ported from the Goa `audio.py`, plus swish, impact, hit, braam, glitch, flash_pop, drop_808, tape_stop, tick, ding, reverse_swell), all peaking between −1.9 and 0 dBFS. User or downloaded packs are added with their licence.
- **Brand kit `goaalm`:** colours #FFB830 / #F4F0E8 / #0C0C0E, fonts Anton + Montserrat + Playfair Display Italic + Mukta/Hind, caption style, grades, and event facts from the Goa session's `event.json` (5th annual, December 2026, 4 PM, Dr. Babasaheb Ambedkar Park, Patto → Azad Maidan, @goaalm, "Liberation is for all."). **To confirm:** the exact date, the handle, the Marathi/Hindi names, a logo.
- **Credits:** all licence sources are merged, grouped (music / footage & photos / SFX / fonts / tools / own work), a CC BY-SA share-alike note is added when needed, and a short caption line is produced. **Unknown licence → refused** (tested with a raw inbox clip).

**Acceptance:** usable 9:16-friendly stock ✅ (Commons; Pexels/Pixabay pending keys) · music index built for ≥ 3 tracks ✅ (5) · credits generate correctly ✅.

**Finding:** ffmpeg's stereo→mono downmix (`-ac 1`) sums identical channels at 1/√2 each, so mono peak readings come out +3 dB. Measure levels on the stereo signal.

## Phase 9: Planning and build layer ✅

**Tools:** `tools/edl.py` (validate + resolve), `tools/snap.py` (anchors, grids), `tools/prep.py` (footage/photo prep), `tools/mix.py` (soundtrack), `tools/build.py` (EDL → HyperFrames page + build.json + render), `tools/fonts.py`, `tools/new_video.py`, `tools/ingest.py`, `tools/audiomap.py`; `docs/recipes/` (13 recipes + EDL cheat-sheet); EDL and build.json schemas in `docs/CONTRACTS.md`.

**How a build works:** the EDL lists clips on one visual track (video, photo, colour card) with in-points, speed or ramps, crop, grade, transitions and fx, plus music, VO, captions, text, SFX, flashes and a brand end card. Cuts with `snap` move to the nearest beat/downbeat/kick/hit/drop/word anchor within a tolerance and are rounded to frames; the anchor is recorded in `build.json`. Every clip is pre-rendered by FFmpeg (trim, speed, RIFE slow motion, reframe, LUT, keyframe every second), then HyperFrames composes scenes, transitions, text, captions and the end card, with one mixed soundtrack.

**Tests:**
- `projects/_test-build` (14 s, shader mode): downbeat/drop snapping (−33/+67 ms moves, frame-rounded), a 1×→0.25× RIFE→1× ramp, a glitch shader, a flash + boom + riser + zoom punch + shake on the drop, a music ride (silence before the drop), a CSS zoom transition, B&W and warm LUTs, an Anton title, a Devanagari title (conjuncts correct), and the GoaALM end card. Build 21 s (first) / 3 s (cached); render 14 s in 31 s. Loudness −13.9 LUFS, −1.9 dBTP. No black frames.
- `projects/_test-build2` (12 s, CSS mode): Marathi edge-tts VO (2 lines), kinetic Devanagari captions from the VO word timings, warm-graded photos with Ken Burns, crossfade, dip-to-black, zoom, a colour card with a Playfair italic quote, a ducked and compressed dhol bed. Render 12 s in 18 s; −14.5 LUFS, −2.0 dBTP.
- `/music-to-video` adapter: Go Cart audiomap corrected from the skill's 57.4 BPM to 115 BPM; key moments moved from whole seconds to exact hits.

**Bugs found and fixed while testing:**
1. HyperFrames' default page-side shader compositing needs the shader-transitions runtime in the page; without it, transitions silently become hard cuts. Fix: vendor `@hyperframes/shader-transitions@0.8.172` (with GSAP) and call `HyperShader.init`.
2. A GSAP `fromTo` applies its start state at once, so a flash at 8 s washed the whole video white. Fix: one timed element per flash; punches as `set` + `to`.
3. A cut written as `data-start="5.0667"` missed the frame at 5.06667 s, giving one black frame. Fix: media start 0.5 ms early.
4. **RIFE on the Arc iGPU intermittently wrote black frames** (2 of 4 identical runs) and once crashed with multi-threading. The Phase 6 eval had passed by luck. Fix: `-j 1:1:1` (clean in 6/6 runs), a check on every output frame with retry, fallback to minterpolate, and the eval now uses the same guarded call (3 identical passing runs, SSIM 0.955, worst frame 0.913).
5. Loudnorm's true-peak landed at −1.4 dBTP (limit −1.5): now aims at −2.0.

**Acceptance:** a sample EDL builds into a HyperFrames project that lints clean and renders ✅ (two test projects covering both render modes). `/plan` itself is Claude's job using the recipes; it is exercised by the Phase 13 demos.

## Phase 10: Review and QA ✅

**Tool:** `tools/review.py` (+ `tools/js/measure_text.mjs`, Puppeteer measurement of real text boxes in Chrome). Checks: technical (size, fps, codec, pixel format, duration ±1 frame, audio), loudness (−14 ±1 LUFS, TP ≤ −1.5 dBTP), black frames outside intended dark parts, frozen picture inside video clips, **cut sync** (biggest picture change within ±0.5 s of each snapped hard cut vs its anchor, ±1 frame), **captions** (no page overlap, words = aligner times ±80 ms, caption band in the safe zone), **safe zone** (every title/end-card line, plus overflow), **glyphs** (every character in its font's cmap: no tofu), brand facts to confirm, licences, `hyperframes check` (lint, runtime, layout, WCAG contrast), optional Gemini review via `agy`. Output: `review/review.json`, `review.md` (with a fix list), `sheet.jpg` (frames at every cut, title, caption page and the end card).

**Acceptance (`tests/make_broken_render.py`):** a clean QA project (`_test-qa`: 4 downbeat-snapped cuts, English VO, pop captions, title) passes all checks. A copy is sabotaged after building (c03 starts 4 frames late, caption page 1 held 0.6 s into page 2, mix +12 dB, title enlarged to 300 px) and re-rendered: the review fails it on **cut_sync** (+3.9 frames), **captions** (pages overlap), **loudness** (−8.5 LUFS) and **safe_zone** (title top at 193 px) ✅.

**Gemini review** (`--gemini`, `agy`, 2 m 29 s): it worked and found a **real bug the automated checks missed**: in the `pop` caption style two neighbouring words both scaled to 1.15 and the gap vanished ("Everyanimal"). Fixed (scale 1.08, wider gap) and verified on the frame. It also flagged the burned-in timecode of our own perception proxy; the review prompt now tells it to ignore that.

**Fixes found while testing:** a render true peak was −1.4 dBTP although the mix measured −1.9 (AAC adds ~0.5 dB of overshoot) → the mix is now mastered to −2.5 dBTP (renders measure −1.9 to −2.4). PySceneDetect missed a cut between two similar dark shots → the cut check now searches for the largest frame difference near each anchor.

**Not built:** automatic "re-render only the changed segment". Renders of 10–30 s videos take 15–35 s, so a full re-render is simpler.

## Phase 11: Export ✅

**Tool:** `tools/export.py` (presets in `config/export_presets.toml`). Master render at `delivery` quality → review → per-preset encode with the project's mastered mix muxed in directly → validation → `poster.jpg`, `CREDITS.txt`, `caption.txt`, `report.md`. Presets with another aspect are rebuilt as **layout variants** from the same EDL (footage re-framed, titles and captions laid out for that format's safe zone) instead of cropping.

**Acceptance (`projects/_test-qa`, 9.5 s, all 7 presets, 3 min 6 s total):**

| Preset | Size | MB | Loudness | Valid |
|---|---|---|---|---|
| reels / shorts | 1080×1920 | 7.5 | −14.7 LUFS | ✅ |
| whatsapp | 720×1280 | 2.0 | −14.7 | ✅ |
| feed45 (variant) | 1080×1350 | 5.9 | −14.7 | ✅ |
| square (variant) | 1080×1080 | 5.1 | −14.7 | ✅ |
| youtube (variant) | 1920×1080 | 9.5 | −14.7 | ✅ |
| master (ProRes 422 HQ) | 1080×1920 | 233.5 | −14.7 | ✅ |

**Fix found:** the 4:5 variant put captions mid-frame (it borrowed Reels-style bottom margins). Safe zones are now per aspect (9:16 Reels UI, 4:5/1:1 6 %, 16:9 title-safe) and the caption band sits on them; checked visually on all four aspects.

## Phase 12: Commands, skill and memory ✅

- 13 slash commands in `.claude/commands/` (BUILD_PLAN §9): /doctor, /new-video, /ingest, /analyze, /perceive, /plan (stops for approval), /build, /review, /export, /music, /stock, /brand, /credits. Each says which tool to run, what to look at, and where to ask the user.
- Studio skill `.claude/skills/studio/SKILL.md`: pipeline table, the §2 rules, language rules, working style.
- `CLAUDE.md` final: rules, how to run, pipeline + commands, one section per phase, folder conventions, fonts, Windows gotchas.
- Claude Code memory for this folder (`~/.claude/projects/D--AI-video-editor-hyperframes/memory/`): user profile; free only / Gemini only via agy; ask before irreversible steps; English words in Latin script in hi/mr captions (mixed mode); prefer OpenVINO int8 models.

## Phase 13: End-to-end acceptance (three demo videos) ✅

All three were planned as EDLs, built, reviewed by `tools/review.py` (contact sheets inspected) and exported with `tools/export.py`. Files in `exports/<slug>/`.

### Demo 1: "Cold Steel" beat-sync montage, 18 s, 9:16 (`exports/demo-beat-montage/`)
Tears of Steel (CC BY 3.0) + "Go Cart – Drop Mix" (Kevin MacLeod, CC BY 4.0). 12 shots, 11 cuts snapped to downbeats/beats/the drop (all within ±1 frame, worst 0.4 f), a glitch shader and a chromatic-split shader, two RIFE speed ramps (1× → 0.25× → 1×, and into 0.3× at the end), a silence ride before the drop, then a riser + boom + white flash + zoom punch + shake on the drop, B&W LUT, Anton slam titles. Review: **PASS, 0 warnings**. −14.0 LUFS / −2.9 dBTP. Exported reels (11.2 MB), whatsapp (3.4 MB), square layout variant (8.2 MB). Build 40 s (first) / render 33 s / export 2 m 44 s.

### Demo 2: GoaALM Marathi promo, 30 s, 9:16 (`exports/demo-marathi-promo/`)
Marathi edge-tts voiceover (6 lines, `mr-IN-AarohiNeural`, MMS word timings), kinetic Devanagari captions word by word (21 pages), 7 Commons photos (dogs, caged hen, cows, goat, a 2019 animal-rights march; CC BY / BY-SA, one upscaled with Real-ESRGAN), cuts snapped to the spoken words (कोंबडी/कुत्रा/गाय/बकरी), B&W first act → light-leak shader into colour, silence + reverse swell + boom + flash on "चला", CC0 dhol-tasha bed ducked under the voice, Marathi GoaALM end card from the brand kit. Review: **PASS** (1 warning: brand facts to confirm). Exported as a **labelled draft** (`--force-unconfirmed`): reels, whatsapp, feed45 variant. CREDITS include the CC BY-SA share-alike note.

### Demo 3: Hindi talking-head reel, 26 s, 9:16 (`exports/demo-hindi-talking-head/`)
From `inbox/hindi.mp4` (it is already 9:16, 720×1280; the plan's 16:9 source was not available): auto-editor silence cut (threshold 16 % for the noisy street audio: 27.8 s → 26.1 s), the known words re-aligned to the cut audio (Flex mixed mode: English words stay in Latin script, e.g. "I don't know what it is", "कर दिया detain", "मेरा left profile"), 7 jump-cut clips reframed on the face with a real-pixel crop zoom (1.4× / 1.75× alternating), zoom punches + a shake on emphasis words, a Hinglish hook title on an amber pill, a low B-Roll comedy bed ducked under speech. Review: everything passes **except licences** (the source is third-party news footage) → exported as a **private draft** (reels, whatsapp).

### Bugs found and fixed while making the demos
1. **HyperFrames lowers the whole soundtrack** when its AAC step overshoots −1 dBTP (it took demo 1 from −13.9 to −16.8 LUFS). Renders now get our own mastered mix muxed back in.
2. **AAC overshoot**: a boom + impact mix mastered to −2.5 dBTP came out at +0.3 dBTP after AAC. Master chain is now 30 Hz high-pass → 5 ms look-ahead limiter → two-pass loudnorm (AAC result about −3 dBTP at −14 LUFS).
3. Commons photos above 3840 px were fetched as 1280 px previews (too small for 9:16 crops). Now the largest standard width below the original is used.
4. Captions on bright photos were unreadable (contrast 1.2–2.9:1). Builds now add soft dark scrims behind the caption band and top titles. Hooks over unknown footage use the `tag` style (solid pill).
5. **Hind draws Devanagari digits like Latin ones** (२०२६ → "2026"); the brand kit and defaults now use Mukta for Devanagari body text.
6. The glyph check caught "→" missing in Hind (the Marathi end card now says "पाटो ते आझाद मैदान").
7. Letter-spacing breaks Devanagari conjunct shaping in Chrome: tracked styles skip it for Devanagari.
8. Word snapping did not work for clip-based captions; the transcript is now mapped through the planned clips first.
9. The cut check now looks for a clear picture change within ±1 frame of the anchor first (jump cuts inside one shot are only a framing change).

---

## Final summary

**Works (measured):** every phase 0–13 passes its acceptance; `tools/doctor.py` is green except the two ⛔ USER warnings (leaked key, optional stock keys).

| Capability | Result |
|---|---|
| Beat analysis | BPM exact on 4 test tracks; drops/kicks to the frame; Go Cart 115 BPM (the HyperFrames skill said 57) |
| Marathi/Hindi ASR | Flex OpenVINO int8: 0.0 % WER on the mr+hi round-trip set (= fp32), ~1.7 s per clip; Marathi 2:55 clip in 93 s |
| Word timing | MMS aligner: 100 % of word starts within 80 ms; caption sync in renders max 32–55 ms |
| Cuts | Shot detection 0-frame error; snapped cuts in renders within ±1 frame (worst 0.4 f) |
| Slow motion | RIFE v4.6 SSIM 0.955 (worst frame 0.913), deterministic after the Arc fix |
| Render speed | 14–30 s videos render in 30–60 s (1080×1920, 30 fps); a full export of 3 presets 2–4 min |
| QA | A deliberately broken render is caught on all 4 counts; Gemini review (agy, ~2.5 min) found a real caption bug |
| Loudness | Every export −14 ±0.3 LUFS, ≤ −1.9 dBTP |

**Known limits / next ideas**
- `"crop": "track"` (moving subject tracking) can't zoom tighter than the full frame height yet; demo 3 used fixed face focus points per clip (fine for a seated speaker, not for someone walking).
- One visual track: picture-in-picture, split screens and text-behind-subject need a hand-made HyperFrames sub-composition (catalog blocks).
- edge-tts needs internet; Kokoro is offline but has no Marathi.
- Gemini via `agy` takes 1–4 min per call and uses AI Pro quota; its timings are only approximate (by design, never used for cuts).
- Real-ESRGAN video upscaling is slow (~0.4 s/frame); photos ~2 min each with x4plus.
- Next: more music in the library (only 5 tracks), a logo for GoaALM, Pexels video once keys exist, track-with-zoom reframing, and lyric-video templates on a real song.

# Data contracts

JSON files the studio tools write and read. Times are **seconds from the start of the source file**, rounded to milliseconds, unless stated otherwise. Each contract is finalised in the phase that builds its producer. Until then, the BUILD_PLAN §8 sketch applies.

| File | Producer | Status |
|---|---|---|
| `analysis/<id>/asset.json` | `tools/assets.py` | ✅ Phase 2 |
| `analysis/<id>/audio.json` | `tools/analyze_audio.py` | ✅ Phase 2 (schema 1) |
| `analysis/<id>/stems/stems.json` | `tools/separate.py` | ✅ Phase 2 |
| `analysis/<id>/transcript.json` | `tools/transcribe.py` | ✅ Phase 3 (schema 1) |
| `analysis/<id>/video.json` (+ `thumbs/`, `sheets/contact.jpg`) | `tools/analyze_video.py` | ✅ Phase 4 (schema 1) |
| `analysis/<id>/siglip.npz` | `tools/index_footage.py` | ✅ Phase 4 |
| `analysis/<id>/reframe_<w>x<h>.json` | `tools/track_subject.py` | ✅ Phase 4 |
| `analysis/<id>/photo.json` | `tools/analyze_photos.py` | ✅ Phase 4 |
| `analysis/<id>/gemini/<preset>-<hash>.json` | Phase 5 | sketch |
| `projects/<slug>/edl.json` | Phase 9 | sketch |

## Asset IDs

`<asset-id>` = first 8 hex chars of the file's SHA-1, then `_`, then the sanitised file stem (ASCII, lower case, `-` separated, ≤ 40 chars). Example: `92ff59a8_go-cart-drop-mix`. Because the ID depends on content, the same file anywhere reuses its cached analysis, and an edited file gets a new ID.

### asset.json

```json
{"asset_id": "92ff59a8_go-cart-drop-mix", "source": "D:\\…\\Go Cart - Drop Mix.mp3",
 "sha1": "92ff59a8…", "registered": "2026-10-19T01:52:10"}
```

## audio.json (schema 1)

```jsonc
{
  "schema": 1,
  "asset_id": "string",
  "source": "absolute path at analysis time",
  "duration": 131.553,                 // s
  "sample_rate": 22050,                // analysis rate (not the file's)
  "loudness": {"I": -7.4, "LRA": 1.3, "TP": 1.5},   // LUFS, LU, dBTP (ffmpeg ebur128)
  "bpm": 115.0,                        // least-squares fit over steady beat runs
  "beat_grid_reliable": true,          // false => recipes pace by phrase/energy, not beat cuts
  "beat_grid": {"reliable": true, "ibi_cv": 0.02, "onset_agreement": 0.94,
                "coverage": 0.9, "reason": "steady grid on onsets"},
  "beat_engine": "beat_this:final0",   // or "librosa.beat_track" (fallback)
  "beats": [0.371, 0.893, …],          // snapped to the nearest precise onset within 35 ms
  "downbeats": [0.371, 2.458, …],
  "onsets": {
    "kick": […], "snare": […], "hihat": […],   // band-jump classified, ~1 ms refined
    "all": […],                                  // every onset (librosa), refined
    "source": "mix" | "drums stem"
  },
  "energy": {"hop": 0.05, "unit": "rms relative to track max", "values": [0.0, 0.12, …]},
  "sections": [
    {"start": 0.0, "end": 4.2, "kick_density": 0.0,   // kicks per beat
     "energy": 0.41,                                    // mean RMS / track max
     "label": "A",          // same letter = same material (timbre, level, kicks); "break" for silences
     "role": "intro" | "low" | "mid" | "high" | "break" | "outro"}
  ],
  "hits":     [{"t": 76.196, "strength": 0.93, "jump_db": 7.1}],   // strong accents
  "silences": [{"start": 129.671, "end": 131.6}],                   // edges ~1 ms
  "drops":    [76.196],              // timed to the first kick of the re-entry
  "tags":     [{"label": "aggressive phonk", "score": 0.803}],      // CLAP top-5, softmax
  "tags_model": "laion/larger_clap_music_and_speech",
  "stems": {"vocals": "path", "drums": "path", "bass": "path", "other": "path", "instrumental": "path"},
  "hyperframes": {                    // `hyperframes audio --quality local` cross-check (informational)
    "kind": "music", "bpm": 115.2, "n_beats": 247, "downbeat_confidence": "low",
    "sections": [{"start": 0, "end": 7.5, "label": "A"}], "provenance": {…}, "warnings": […]
  },
  "timings_s": {"beats": 6.0, "onsets_energy": 2.8, "sections": 0.5, "tags": 20.1, "hyperframes": 4.7, "total": 34.1},
  "created_at": "2026-10-19T01:55:00"
}
```

`hits`, `drops`, `kick` and `silences` are the anchors that cuts snap to (Phase 9). `beats`/`downbeats` are only for snapping when `beat_grid_reliable` is true.

## stems/stems.json

```jsonc
{"runs": {
  "htdemucs.yaml": {
    "stems": {"bass": "…/stems/htdemucs/bass.wav", "drums": "…", "instrumental": "…", "other": "…", "vocals": "…"},
    "seconds": 71.3, "audio_seconds": 131.6, "rtf": 0.54, "device": "cpu", "created_at": "…"},
  "model_bs_roformer_ep_317_sdr_12.9755.ckpt": {"stems": {"instrumental": "…", "vocals": "…"}, …}
}}
```

One folder per model under `analysis/<id>/stems/`. Stem WAVs are 44.1 kHz stereo 16-bit.

## transcript.json (schema 1)

```jsonc
{
  "schema": 1, "asset_id": "4dd39978_speech-mr-f", "source": "…",
  "key": "mr-script",                  // <lang>-<script|engine>[-vocals]: the cache key
  "language": "mr" | "hi" | "en",
  "engine": "mms-align:script" | "parakeet-tdt-0.6b-v3+mms-align" | "indic-transcribe-core[ov-cpu/int8]+mms-align",
  "audio": "mix" | "vocal stem",
  "duration": 11.208,
  "text": "the script/lyrics that were aligned, or null for ASR",
  "words": [{"text": "गोव्यातील", "start": 0.23, "end": 0.95, "conf": 0.81, "low_conf": true}],
  "cues":  [{"start": 0.23, "end": 1.83, "text": "गोव्यातील प्राणी मुक्ती", "words": [0, 1, 2]}],
  "low_conf_words": ["…"],             // alignment conf < 0.05 (~bottom 5 % on real speech)
  "timings_s": {"asr": 4.0, "align": 1.5, "total": 5.9}, "rtf": 0.53,
  "created_at": "…"
}
```

- `words[].text` keeps the original script (Devanagari, punctuation attached). Timings are aligner timings, with the bias correction from `[align]` in `config/studio.toml` applied. `low_conf` appears only on flagged words.
- `cues` come from `tools/captions.py`: ≤ 4 words, ≤ 24 characters, ≤ 2.6 s, a break after a pause ≥ 0.45 s or at `. ! ? ।`, held 0.25 s after the last word but never overlapping the next cue.
- `transcript.srt` and `transcript.vtt` sit next to it. For a HyperFrames project, `tools/captions.py --hf projects/<slug>/transcript.json` (or `transcribe.py --hf`) writes the flat `[{id, text, start, end}]` array HyperFrames uses.

## video.json (schema 1)

```jsonc
{
  "schema": 1, "asset_id": "32c187bc_tos-60-180", "source": "…",
  "meta": {"w": 1920, "h": 800, "fps": 24.0, "duration": 120.0, "rotation": 0, "codec": "h264",
           "pix_fmt": "yuv420p", "bit_depth": 8, "hdr": false, "color_transfer": null,
           "audio": true, "audio_codec": "aac", "frames": 2880},   // w/h in display orientation
  "shot_detector": "scenedetect AdaptiveDetector(adaptive_threshold=3.0) + ThresholdDetector(12)",
  "shots": [{
    "index": 0, "start": 0.0, "end": 4.458, "duration": 4.458,
    "transition_in": null | "cut" | "fade",       // how this shot begins
    "motion": 1.2, "motion_peak": 3.4,            // optical flow, % of frame width per second
    "pan": [0.3, -0.1],                           // median flow (x, y), same unit: camera pan/tilt
    "sharpness": 812.3, "sharpness_rank": 0.1,    // Laplacian variance at 640 px; rank 0..1 in this video
    "brightness": 0.38, "contrast": 0.21, "colourfulness": 31.5,
    "faces": {"present": 1.0, "max_count": 1,     // share of samples with a face
              "largest": {"x": 0.42, "y": 0.31, "w": 0.12, "h": 0.2, "score": 0.93}},  // 0..1 of frame
    "best_t": 2.75, "thumb": "thumbs/shot_000.jpg"
  }],
  "cuts": [4.458, …],                             // shot starts after the first
  "fades": [{"start": 15.0, "end": 15.5, "kind": "black"}],   // >= 0.25 s near black in the samples
  "best_frames": [{"shot": 17, "t": 95.5}],       // sharp, well exposed, faces preferred
  "samples": {"fps": 4.0, "width": 640, "values": [{"t", "sharpness", "brightness", "contrast",
              "colourfulness", "motion", "pan", "faces": [{x, y, w, h, score}]}]},
  "contact_sheet": "sheets/contact.jpg", "timings_s": {…}, "created_at": "…"
}
```

## siglip.npz

NumPy archive: `t` (float32 seconds; photos: 0), `shot` (int32 shot index), `emb` (float16, L2-normalised, 768-d), `model`, `kind` (`video`|`photo`). Videos: one frame per second (`--every`) plus every shot's `best_t`.

## reframe_<w>x<h>.json

```jsonc
{"asset_id": "…", "source": "…", "aspect": "9:16", "src": [1920, 800], "crop": [450, 800], "fps": 24.0,
 "method": "YuNet faces > EfficientDet people > spectral-residual saliency; per shot: gap fill 1.5s, …",
 "path": [{"t": 56.7, "x": 802, "y": 0}],          // one per output frame: crop top-left, source px
 "samples": [{"t", "target_x", "smooth_x", "cue": "faces"|"people"|"saliency", "faces": […]}]}
```

The crop jumps only on cuts; within a shot it is smoothed. `track_subject.py --render` applies it with ffmpeg `sendcmd`; HyperFrames can drive a `translateX` from `path`.

## photo.json

```jsonc
{"asset_id": "…", "source": "…", "w": 1920, "h": 800,     // after EXIF orientation
 "megapixels": 1.54, "exif_orientation": 6, "rotated": true, "taken": "2024:03:01 10:22:01", "camera": "…",
 "sharpness": 260.0, "blurry": false,                     // Laplacian variance at 1024 px; blurry < 60
 "brightness": 0.31, "clipped_highlights": 0.002, "crushed_shadows": 0.04,
 "faces": [{x, y, w, h, score}], "focus": [0.62, 0.35], "focus_by": "face"|"saliency",
 "crop_916": [450, 800], "needs_upscale_916": true,      // largest 9:16 crop; < 1920 tall needs upscaling
 "crop_169": [1422, 800], "needs_upscale_169": true,
 "phash": "…", "created_at": "…"}
```

`analyze_photos.py` adds `duplicate_of` / `keep` across a set (not stored in photo.json, since that depends on the set).

## gemini/<preset>_<hash>.json (Phase 5)

`{preset, model, effort, prompt_hash, canaries:{passed, details}, result:{…preset schema…}, raw, created_at, route:"agy"|"relay"}`; see tools/perceive.py.

## edl.json (Phase 9, written by /plan, read by tools/build.py)

Times are timeline seconds. Paths are relative to the studio root, absolute, or `./…` relative to the project.

```jsonc
{
  "title": "GoaALM Marathi promo", "recipe": "promo",
  "format": "reels",                       // or {"w": 1080, "h": 1920, "fps": 30}; reels|shorts|feed45|square|youtube|whatsapp
  "duration": 30.0,                        // required unless the last clip has `until`
  "brand": "goaalm",                       // library/brands/<brand>/brand.json (fonts, colours, end card, safe zone)
  "grade": "warm_film",                    // default LUT (library/luts) for clips/photos; "none" to skip
  "bg": "#000000",
  "music": {"src": "library/music/…mp3", "from": 12.0, "at": 0.0, "until": 30.0,
            "gain_db": 0, "fade_in": 0.02, "fade_out": 1.5, "duck_db": -9, "compress": false,
            "rides": [{"from": 7.6, "to": 8.15, "db": -24}]},
  "vo": {"lang": "mr", "voice": "mr_f", "rate": "+0%", "start": 0.5, "gap": 0.35,      // or "script": "./vo_script.json"
         "lines": [{"id": "l01", "text": "…", "at": 0.6}]},                              // `at` optional (sequential)
  "captions": {"src": "vo" | "clips" | "analysis/<id>/transcript.json", "offset": 0, "range": [t0, t1],
               "style": "kinetic"|"pill"|"pop", "font": "Mukta", "max_words": 3, "max_chars": 22, "size": null},
  "clips": [                               // one visual track, sorted by `at`
    {"id": "c01", "src": "inbox/a.mp4", "in": 12.4, "at": 0.0, "until": null,
     "speed": 1.0,                         // or "ramp": [{"dur": 0.6, "speed": 1}, {"dur": 1.4, "speed": 0.25, "rife": true}, {"speed": 1}]
     "crop": "center" | "track" | {"x": 0.4, "y": 0.5},
     "grade": "bw_contrast", "audio": false | true | {"gain_db": -3, "normalize": true},
     "snap": {"to": "beat|downbeat|kick|snare|onset|hit|drop|section|word|word_end", "tol": 0.12},
     "transition": {"type": "cut|fade|dip|flash|zoom|whip|<shader>", "dur": 0.4},
     "fx": [{"type": "zoom_punch", "at": 8.2, "amount": 1.12, "dur": 0.3}, {"type": "shake", "at": 8.2, "dur": 0.3, "amount": 18},
            {"type": "push_in", "to": 1.08}, {"type": "pull_out", "from": 1.1}, {"type": "flash", "at": 8.2, "dur": 0.25, "peak": 0.9}],
     "kenburns": {"from": 1.0, "to": 1.12, "focus": [0.5, 0.4]}},          // photos
    {"id": "c09", "color": "#0C0C0E", "at": 26.0}                            // solid card
  ],
  "flashes": [{"at": 8.196, "dur": 0.3, "color": "#FFFFFF", "peak": 0.9}],
  "text": [{"content": "…", "at": 1.0, "until": 3.0, "style": "title|big|subtitle|tag|lower|quote",
            "anim": "slam|pop|rise|fade|type|words|none", "word_times": [..], "pos": "center|top|bottom|lower",
            "font": null, "size": null, "color": null, "highlight": ["word"], "out": "fade", "upper": true}],
  "sfx": [{"name": "boom", "at": 8.196, "gain_db": 0}, {"src": "./whoosh.wav", "at": 3.0, "align": "onset|end"}],
  "endcard": {"at": 26.0, "until": 30.0, "lines": null},                    // lines default to brand.end_card
  "models": ["rife"], "caption_post": "…", "hashtags": ["#GoaALM"]
}
```
Shader transitions (`glitch`, `chromatic-split`, `cinematic-zoom`, `cross-warp-morph`, `domain-warp`, `flash-through-white`, `gravitational-lens`, `light-leak`, `ridged-burn`, `ripple-waves`, `sdf-iris`, `swirl-vortex`, `thermal-distortion`, `whip-pan`) switch the page to HyperShader mode (all scenes managed by `@hyperframes/shader-transitions`, vendored in `library/vendor`).

## build.json (Phase 9, written by tools/build.py; read by review, export, credits)

`{title, slug, recipe, built_at, format:{w,h,fps}, duration, shader_mode, cuts:[{clip, t, planned, anchor, kind}], clips:[{id, kind, path, at, until, tl_start, tl_end, src_in, src_out, segments, transition, fx, media}], text:[{content, at, until, style, pos}], endcard:{lines, at, until}|null, captions:{cues:[{start,end,text}], words, engine}|null, vo:[{id, at, duration, text, lang, engine}], music, sfx, loudness:{I, LRA, TP}, safe_zone:{top,bottom,left,right}, fonts[], models[], assets:[{path}], unconfirmed_facts[], warnings[], brand, caption_post, hashtags, build_seconds, render?:{file, seconds}}`

`cuts[].anchor` is the music/word time the cut was snapped to (null = unsnapped); `/review` checks the rendered cut lands within ±1 frame of it.

## review.json and report (Phase 10) / export (Phase 11)

See tools/review.py and tools/export.py docstrings: `review.json = {render, checks:[{name, status: pass|warn|fail, detail}], fixes:[…], sheet, gemini?}`.

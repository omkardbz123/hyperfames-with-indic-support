# AI Video Studio

A free, local video-editing studio driven by Claude Code, built on [HyperFrames](https://hyperframes.heygen.com) (HTML/GSAP → Chrome → FFmpeg). It makes promos, beat-sync edits, talking-head reels, lyric videos, slideshows, explainers, trailers, subtitles/dubs and restorations, with **Marathi and Hindi as first-class languages** (transcription, Devanagari captions, voiceover).

Everything runs on your own computer. The only online pieces are free: edge-tts voices, Wikimedia/Openverse stock search, and (optionally) Gemini 3.8 Flash through the Antigravity app (`agy`, never the Gemini API).

## Install (Windows 10/11)

```bat
git clone https://github.com/omkardbz123/hyperfames-with-indic-support.git ai-video-studio
cd ai-video-studio
installation.bat
```

`installation.bat` checks what is already on the computer and installs only what is missing (Git, uv, Node.js, FFmpeg full build, Chrome, the Python and Node packages, tools and models), asking before each step. **[SETUP.md](SETUP.md)** is the step-by-step guide with every link, the free Hugging Face sign-up for the Marathi/Hindi model, and troubleshooting. About 20 GB of disk.

## Everyday use (talk to Claude in this folder)

1. **Drop your files** (clips, photos, music, a script) into `inbox/`.
2. **Start a video:** `/new-video goa-march-promo promo` (recipes: beat-sync, promo, talking-head, lyric, slideshow, explainer, trailer, tutorial, subtitles-dub, recap, restoration, meme, repurpose). Claude asks for whatever the brief still needs.
3. **Ingest + analyse:** `/ingest goa-march-promo`, then `/analyze goa-march-promo`. Claude asks whether the files are yours (for the credits) and studies the music beats, the shots, the speech and the photos.
4. **Plan:** `/plan goa-march-promo` writes `plan.md` (what happens when, which music, which shots, every on-screen text in every language, the voiceover script). **You approve or change it.**
5. **Build + review:** `/build goa-march-promo`, then `/review goa-march-promo` (add `--gemini` for a watch-through by Gemini). The review checks sync, loudness, captions, safe zones, missing letters, licences and facts, and shows a contact sheet.
6. **Export:** `/export goa-march-promo reels,whatsapp` → `exports/goa-march-promo/`: the videos, `poster.jpg`, `CREDITS.txt`, `caption.txt` (paste into Instagram, credit line included) and `report.md`.

Changes are just conversation: "move the title to the drop", "make the captions bigger", "use the second dhol track", "change the date". Claude edits `edl.json` and rebuilds.

Other commands: `/music add|find "sad piano"`, `/stock "street dog india"`, `/brand goaalm`, `/credits <slug>`, `/perceive <file> find_moments`, `/doctor` (health check).

## What it can do

| Area | How |
|---|---|
| Beat sync | Beats, downbeats, kicks, drops from Beat This! + our onset analysis; cuts snap to them (±1 frame, checked in review) |
| Speech | Marathi/Hindi: Indic-Transcribe-Flex (OpenVINO int8, local), English: Parakeet; word timings from the MMS aligner; English words stay in Latin script in Hinglish/Marathi-English speech |
| Captions | Word-synced kinetic / pill / pop captions in Devanagari + Latin (Mukta), never overlapping, inside safe zones |
| Voiceover | edge-tts Marathi/Hindi/English voices (online, free) or Kokoro (offline, no Marathi) |
| Footage | Shot detection, search by description, auto-reframe to 9:16, slow motion (RIFE), upscaling (Real-ESRGAN), stabilising, silence cutting, voice denoising, LUT looks |
| Effects | Shader transitions (glitch, light leak, whip pan…), flashes, zoom punches, shake, Ken Burns, speed ramps, titles, brand end cards |
| Sound | Music bed with ducking under voices, rides (silence before a drop), synthesised SFX, mastered to −14 LUFS |
| Credits | Every asset carries its licence; exports refuse unknown licences and unconfirmed brand facts |

## Demos

`exports/demo-beat-montage/`, `exports/demo-marathi-promo/`, `exports/demo-hindi-talking-head/` (see `docs/STATUS.md` → Phase 13).

## Where things are

`docs/STATUS.md` (what works, measurements, open items) · `docs/recipes/` · `docs/CONTRACTS.md` (file formats) · `docs/BUILD_PLAN.md` (the original plan) · `CLAUDE.md` (rules for Claude) · `library/` (music, sfx, luts, fonts, brands, stock) · `projects/<slug>/` (one folder per video) · `tools/` (every tool has `--help`).

Rules the studio always follows: free only; Gemini only via Antigravity; precise timing from local analysis, never from Gemini; credits on every export; nothing deleted without asking (scratch goes to `_trash/`).

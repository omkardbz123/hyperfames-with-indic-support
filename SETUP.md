# Setup guide

This guide gets the AI Video Studio running on a new Windows computer. The short version:

1. Install Git and download this folder (step 1).
2. Double-click **`installation.bat`**.
3. Answer its questions.

The installer checks every item below. It installs only what is missing, and it asks before each install or download. You can run it again whenever you like: finished steps are skipped.

The rest of this page explains each step, in case you want to do it by hand or something goes wrong.

## What you need

| | |
|---|---|
| Computer | Windows 10 or 11, 64-bit. 16 GB RAM recommended (8 GB works for short videos). |
| Disk | About **20 GB free**: models ~8 GB, tools ~4 GB, plus room for your videos. |
| Graphics | Any. A GPU with Vulkan (Intel Arc / NVIDIA / AMD) makes slow motion and upscaling faster. Everything else runs on the CPU. |
| Internet | Only for setup. After that, everything runs on your own computer except the edge-tts voices and stock-photo search. |
| Accounts | **Hugging Face** (free): needed for the Marathi/Hindi speech model.<br>**Claude** (paid plan, Pro or Max): needed for Claude Code, the assistant that drives the studio.<br>**Google AI Pro**: optional, only for Gemini reviews. |

Everything else in the studio is free.

## Step 1: Get the folder

1. Install **Git**. Either:
   - download it from https://git-scm.com/download/win and click Next through the installer (the defaults are fine), or
   - in a terminal, run `winget install --id Git.Git -e`.
2. Choose a drive with space; in this example, `D:` is that drive. Open a terminal there and run:

   ```bat
   cd /d D:\
   git clone https://github.com/omkardbz123/hyperfames-with-indic-support.git ai-video-studio
   cd ai-video-studio
   ```

   Pick a short path **without** spaces if you can (`D:\ai-video-studio`).
3. Double-click `installation.bat`, or run it from the terminal.

## Step 2: Programs (the installer does these with `winget`)

| # | Program | Why | Installer command | Manual download |
|---|---|---|---|---|
| 2 | Git | updates, plus one Python package that comes from GitHub | `winget install Git.Git` | https://git-scm.com/download/win |
| 3 | uv | installs Python 3.11 and the packages, inside this folder only | `winget install astral-sh.uv` | https://docs.astral.sh/uv/getting-started/installation/ |
| 4 | Node.js 22 or newer | runs HyperFrames, the renderer | `winget install OpenJS.NodeJS.LTS` | https://nodejs.org/en/download |
| 5 | FFmpeg **full** build (Gyan) | video and audio engine | `winget install Gyan.FFmpeg` | https://www.gyan.dev/ffmpeg/builds/ |
| 6 | Google Chrome | the review step measures text in Chrome | `winget install Google.Chrome` | https://www.google.com/chrome/ |

If winget is missing, install **App Installer** from the Microsoft Store: https://apps.microsoft.com/detail/9NBLGGH4NNS1

**FFmpeg must be the FULL build.** "Essentials" builds don't have the stabilise, LUT and motion-interpolation filters. The studio picks the Gyan full build even when other FFmpeg copies are on your PATH. To use a manual download instead, unzip `ffmpeg-release-full.7z` so that `bin\ffmpeg\bin\ffmpeg.exe` exists inside this folder.

> After winget installs something, Windows sometimes only sees it in a **new** terminal window. If the installer says a program is still missing, close the window and run `installation.bat` again.

## Step 3: Python packages (about 3 GB)

```bat
uv sync
uv sync --reinstall-package opencv-contrib-python
```

uv downloads its own Python 3.11 into `.venv\` in this folder. Your system Python is not touched. The second line fixes a known package clash: `scenedetect` pulls in plain OpenCV, and the contrib build has to win.

## Step 4: HyperFrames (about 300 MB)

```bat
npm ci
```

This installs HyperFrames 0.8.172 (Apache-2.0) into `node_modules\`. Always run it through `uv run tools\hf.py …`, never `npx hyperframes`. The wrapper:
- pins the right FFmpeg;
- turns off telemetry;
- keeps caches inside this folder;
- removes cloud API keys from the environment.

## Step 5: Tools and models: `uv run tools\setup.py`

The installer runs this for you. It goes through 14 items. Each item checks what is already there, then asks before downloading. Downloads land in `_dl\` first and are checked against a recorded SHA-256 fingerprint; a file that doesn't match is refused.

| Item | Size | Licence | Used for |
|---|---|---|---|
| config | – | – | writes `config\studio.local.toml` with this computer's FFmpeg / Chrome paths |
| render browser | ~150 MB | BSD | HyperFrames renders the video in headless Chrome |
| fonts | ~40 MB | OFL | Mukta, Noto Devanagari, Hind, Tiro, Baloo 2, Montserrat… (Devanagari + Latin) |
| sfx | – | own work | 15 synthesised whooshes, hits, risers |
| vision | 8 MB | MIT / Apache-2.0 | face and person detection for auto-reframing |
| RIFE | 827 MB | MIT | slow motion (frame interpolation) |
| Real-ESRGAN | 45 MB | BSD-3 | upscaling photos and video |
| DeepFilterNet | 27 MB | MIT / Apache-2.0 | removing noise from voice recordings |
| auto-editor | 30 MB | Unlicense | cutting silences |
| Parakeet | 640 MB | CC-BY-4.0 | English speech-to-text |
| **Indic-Transcribe** | 1.2 GB | Indic Open Model License | **Marathi/Hindi speech-to-text** (step 6 below) |
| analysis models | ~4.3 GB | various | beat tracking, music mood, word timing, footage search, stem separation. If you say no, each one downloads the first time a tool needs it. |
| agy | – | – | optional, Gemini reviews (step 8) |

To run only some items: `uv run tools\setup.py --only indic,rife`. To see what is missing without changing anything: `uv run tools\setup.py --check`.

## Step 6: Marathi/Hindi speech model (free account, one-time licence)

The studio uses **Indic-Transcribe-Flex** from Bodhan AI / AI4Bharat. It runs as a fast int8 OpenVINO version on your CPU. The model is free, but you must accept its licence once:

1. Create a free account: https://huggingface.co/join (and confirm your email).
2. Open https://huggingface.co/omkar9896/indic-transcribe-openvino-int8
3. Fill in the short form (organisation, country, use) and click **Agree and access repository**. Approval is automatic.
4. Create a token:
   1. Go to https://huggingface.co/settings/tokens.
   2. Click **Create new token**.
   3. Choose type **Read** and give it any name.
   4. Click **Create** and copy the token.
5. When `setup.py` asks "Log in to Hugging Face now?", answer **Y** and paste the token. Nothing shows while you paste, which is normal. Press Enter.

   Or do it yourself: `uv run hf auth login`, then `uv run tools\setup.py --only indic`.

The token is saved in your Windows user folder (`%USERPROFILE%\.cache\huggingface\token`), **never in this repo**. Don't share it, and don't paste it into any file here.

Any video whose captions came from this model must carry the line **"Built with Indic-Transcribe-Flex from Bodhan AI / AI4Bharat."** The credits tool adds it automatically. The licence also forbids certain uses (Section 10: surveillance, impersonation, disinformation and similar); read [the licence](https://huggingface.co/omkar9896/indic-transcribe-openvino-int8/blob/main/LICENSE_DEED.md).

## Step 7: Claude Code (the assistant)

You talk to Claude Code in plain language ("make a 30 s reel from these clips"), and it runs every tool for you. Install either:
- **Claude desktop app**, Code tab: https://claude.ai/download, or
- **the command line**: https://docs.claude.com/en/docs/claude-code/setup. The installer can run the official `irm https://claude.ai/install.ps1 | iex` for you.

Claude Code needs a paid Claude plan (Pro or Max). Without it, every tool still works by hand: `uv run tools\<tool>.py --help`.

Open **this folder** in Claude Code. It reads `CLAUDE.md` (the studio rules) and the `/commands` automatically.

## Step 8: Gemini reviews (optional)

`/review --gemini` and `/perceive` ask Gemini to watch a render. This uses the **Antigravity CLI `agy`** with a Google account that has **Google AI Pro**:
1. Install it from https://antigravity.google/cli.
2. Run `agy` once in a terminal and sign in.

**Never use a Gemini API key** with this studio. Without agy, use `perceive.py --relay`: it writes a prompt you paste into the Gemini app yourself.

## Step 9: Check everything

```bat
uv run tools\doctor.py
```

- Every line should be `ok`.
- `warn` lines are optional extras (Pexels/Pixabay keys, Docker, Gemini).
- `FAIL` lines show the exact fix in the last column.

## Your first video

In Claude Code, inside this folder:

```
/doctor
/new-video my-first-reel promo
```

1. Put your clips, photos and music in `inbox\`.
2. Then run `/ingest my-first-reel` → `/analyze my-first-reel` → `/plan my-first-reel`.
3. Read and approve the plan.
4. Run `/build my-first-reel` → `/review my-first-reel` → `/export my-first-reel reels,whatsapp`.
5. The finished files appear in `exports\my-first-reel\`, with `CREDITS.txt` and a ready-to-paste `caption.txt`.

See [README.md](README.md) for everything the studio can do, and `docs\recipes\` for the 13 video types.

## Keeping it up to date

```bat
git pull
installation.bat
```

## Troubleshooting

| Problem | Fix |
|---|---|
| "X is not recognized" right after installing X | Close the terminal, open a new one, and run `installation.bat` again. |
| `uv sync` fails on `ctc-forced-aligner` | Git is missing or not on PATH: install Git, then reopen the terminal. |
| doctor: ffmpeg "missing filters" | It found an essentials build. Run `winget install Gyan.FFmpeg`, then `uv run tools\setup.py --only config`. |
| Hugging Face: "No access yet (GatedRepoError)" | Accept the licence on the model page **with the same account** that made the token. |
| Hugging Face: 401 / invalid token | Make a new **Read** token and run `uv run hf auth login` again. |
| edge-tts voice fails with 403 | `uv pip install -U edge-tts` |
| RIFE / Real-ESRGAN: "vkCreateInstance failed" | Update your graphics driver (Vulkan). These two tools also work on another GPU index: `[gpu] vulkan_device` in `config\studio.local.toml`. |
| Slow renders | Close other apps. `[render] workers` in `config\studio.local.toml` (default 6) can go down on 4-core laptops. |
| A download was "refused (SHA-256 mismatch)" | Nothing was installed. Try again later. If it keeps failing, tell the maintainer: the upstream file changed. |

Machine-specific settings go in `config\studio.local.toml` (any key from `config\studio.toml` can be overridden there). That file is git-ignored, so `git pull` never overwrites it.

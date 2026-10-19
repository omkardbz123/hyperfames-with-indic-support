"""First-time setup (and repair) for a new computer. installation.bat runs this after uv + npm.

Usage:  uv run tools/setup.py            (interactive: checks everything, asks before each download)
        uv run tools/setup.py --check    (only report what is missing)
        uv run tools/setup.py --yes      (say yes to every download)
        uv run tools/setup.py --only indic,rife   (just these steps)

Steps: config, browser, fonts, sfx, luts, vision, rife, realesrgan, deepfilter, auto-editor,
parakeet, indic, models, agy. Every step first checks what is already there and skips it.
Downloads go to _dl/<tool>/ first and are checked against a recorded SHA-256 before use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()
cfg.model_cache_env()

ROOT = cfg.ROOT
PY = sys.executable
VENV_BIN = Path(PY).parent
DL = ROOT / "_dl"
INDIC_REPO = "omkar9896/indic-transcribe-openvino-int8"

# Official release builds only (BUILD_PLAN §2.6). sha = the download, exe_sha = the extracted executable.
BINARIES = {
    "rife": {
        "url": "https://github.com/TNTwise/rife-ncnn-vulkan/releases/download/20250112/windows.zip",
        "size_mb": 827, "sha": "42ed35e115b026f222386648920218cb8a9c7ae1e23698a7363bdd2e1455aba3",
        "exe": "rife-ncnn-vulkan.exe", "exe_sha": "ddee627a5342e6ac4456625921b8d5ff52c2b459102c1c220106623ae358725a",
        "what": "slow motion / frame interpolation (fx.py slowmo)",
        "version": "TNTwise/rife-ncnn-vulkan 20250112 — windows.zip (826923873 bytes)\n"
                   "https://github.com/TNTwise/rife-ncnn-vulkan/releases/tag/20250112\n"
                   "MIT (code); RIFE models MIT (hzwer/Practical-RIFE)"},
    "realesrgan": {
        "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip",
        "size_mb": 45, "sha": "abc02804e17982a3be33675e4d471e91ea374e65b70167abc09e31acb412802d",
        "exe": "realesrgan-ncnn-vulkan.exe", "exe_sha": "07e49f7cbb4ede01ae4dd4c399d3a7e5846e3d2085c3128eff881e55cb7b1a0c",
        "what": "photo / video upscaling (fx.py upscale)",
        "version": "xinntao/Real-ESRGAN v0.2.5.0 — realesrgan-ncnn-vulkan-20220424-windows.zip\n"
                   "https://github.com/xinntao/Real-ESRGAN/releases/tag/v0.2.5.0\nBSD-3-Clause"},
    "deepfilter": {
        "url": "https://github.com/Rikorose/DeepFilterNet/releases/download/v0.5.6/deep-filter-0.5.6-x86_64-pc-windows-msvc.exe",
        "size_mb": 27, "sha": "75e11fa16445f560cb6b021521ddb89e89270d13b83089705d98776f58fd7915",
        "exe": "deep-filter.exe", "exe_sha": "75e11fa16445f560cb6b021521ddb89e89270d13b83089705d98776f58fd7915",
        "what": "voice noise removal (fx.py denoise-voice)",
        "version": "Rikorose/DeepFilterNet v0.5.6 — deep-filter-0.5.6-x86_64-pc-windows-msvc.exe (DeepFilterNet3 model built in)\n"
                   "https://github.com/Rikorose/DeepFilterNet/releases/tag/v0.5.6\nMIT / Apache-2.0"},
}

VISION = [  # (target under cache/, url, sha256)
    ("opencv/face_detection_yunet_2023mar.onnx",
     "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
     "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    ("mediapipe/blaze_face_short_range.tflite",
     "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite",
     "b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f"),
    ("mediapipe/efficientdet_lite0.tflite",
     "https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/float16/latest/efficientdet_lite0.tflite",
     "4b59100025bea1235a84c1038879a6cccc9f6c49f5e41144e91e74d99e780993"),
]

AUTO_EDITOR_SHA = "ba8eecd647355359436b7088d61ffa7a9ea07a88dc121b999cc337b882400c05"   # GitHub digest, 29.3.1

FFMPEG_FILTERS = ["drawtext", "lut3d", "vidstabdetect", "vidstabtransform", "minterpolate",
                  "ebur128", "loudnorm", "blackdetect", "freezedetect"]

A: argparse.Namespace
RESULTS: list[tuple[str, str, str]] = []   # (step, status, note)


# ---------------------------------------------------------------- helpers

def say(msg: str = "") -> None:
    print(msg, flush=True)


def head(n: int, total: int, title: str) -> None:
    say(f"\n=== [{n}/{total}] {title} " + "=" * max(3, 60 - len(title)))


def ask(question: str, default: bool = True) -> bool:
    if A.check:
        return False
    if A.yes:
        say(f"{question} -> yes (--yes)")
        return True
    hint = "[Y/n]" if default else "[y/N]"
    try:
        r = input(f"{question} {hint} ").strip().lower()
    except EOFError:
        return default
    return default if not r else r.startswith("y")


def done(step: str, status: str, note: str = "") -> None:
    RESULTS.append((step, status, note))
    mark = {"ok": "OK", "installed": "INSTALLED", "skipped": "SKIPPED", "missing": "MISSING", "failed": "FAILED"}[status]
    say(f"  -> {mark}{': ' + note if note else ''}")


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, want_sha: str) -> Path:
    """Download into dest (unless an identical file is already there); refuse on a hash mismatch."""
    if dest.exists() and sha256(dest) == want_sha:
        say(f"  already downloaded: {dest}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    say(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "ai-video-studio-setup"})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        got, last = 0, -1
        while chunk := r.read(1 << 20):
            f.write(chunk)
            got += len(chunk)
            pct = int(got * 100 / total) if total else -1
            if pct != last and (pct % 5 == 0 or pct < 0):
                print(f"\r  {got / 1e6:8.1f} MB" + (f" / {total / 1e6:.1f} MB ({pct}%)" if total else ""), end="", flush=True)
                last = pct
    print()
    h = sha256(tmp)
    if h != want_sha:
        bad = tmp.with_suffix(".UNTRUSTED")
        tmp.replace(bad)
        raise RuntimeError(f"SHA-256 mismatch for {url}\n  got {h}\n  expected {want_sha}\n"
                           f"  NOT installed; the file is kept as {bad} for inspection.")
    tmp.replace(dest)
    return dest


def run(cmd: list[str], **kw) -> int:
    say("  $ " + " ".join(f'"{c}"' if " " in c else c for c in cmd))
    return subprocess.run(cmd, cwd=ROOT, **kw).returncode


def uv_tool(script: str, *args: str) -> list[str]:
    return [PY, str(ROOT / "tools" / script), *args]


# ---------------------------------------------------------------- steps

def step_config() -> None:
    """Find FFmpeg (full build), Chrome and agy on this computer; write config/studio.local.toml."""
    found = {}
    ff = cfg.ffmpeg()
    if not Path(ff).exists() and not shutil.which(ff):
        done("config", "missing", "FFmpeg not found. Run installation.bat (it installs winget Gyan.FFmpeg), "
             "or download the FULL build from https://www.gyan.dev/ffmpeg/builds/ and unzip it into bin/ffmpeg/")
        return
    out = subprocess.run([ff, "-hide_banner", "-filters"], capture_output=True, text=True, errors="replace").stdout
    miss = [n for n in FFMPEG_FILTERS if not re.search(rf"\s{n}\s", out)]
    if miss:
        done("config", "failed", f"{ff} is not a FULL build (missing {miss}). Install it: winget install Gyan.FFmpeg")
        return
    found["ffmpeg"], found["ffprobe"] = ff, cfg.ffprobe()
    chrome = cfg.path("chrome")
    if chrome.exists():
        found["chrome"] = str(chrome)
    agy = cfg.agy()
    say(f"  ffmpeg : {found['ffmpeg']}\n  ffprobe: {found['ffprobe']}\n  chrome : {found.get('chrome', 'not found (optional, review uses it)')}"
        f"\n  agy    : {agy or 'not installed (optional)'}")
    if A.check:
        done("config", "ok" if cfg.LOCAL.exists() else "missing", "config/studio.local.toml" + ("" if cfg.LOCAL.exists() else " not written yet"))
        return
    lines = ["# This computer's own paths (git-ignored). Written by tools/setup.py; edit freely.",
             "# Anything here overrides config/studio.toml.", "", "[paths]"]
    lines += [f"{k} = '{v}'" for k, v in found.items()]
    if agy:
        lines += ["", "[gemini]", f"agy_path = '{agy}'"]
    if cfg.LOCAL.exists():
        old = cfg.LOCAL.read_text(encoding="utf-8")
        if old.strip() == "\n".join(lines).strip():
            done("config", "ok", "config/studio.local.toml up to date")
            return
        backup = ROOT / "_trash" / "studio.local.toml.bak"
        backup.parent.mkdir(exist_ok=True)
        backup.write_text(old, encoding="utf-8")
    cfg.LOCAL.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cfg.load.cache_clear()
    done("config", "installed", "wrote config/studio.local.toml")


def step_browser() -> None:
    """HyperFrames' render browser (chrome-headless-shell, ~150 MB, into your user cache)."""
    if A.check:
        done("browser", "skipped", "checked by doctor")
        return
    rc = run(uv_tool("hf.py", "browser", "ensure"))
    done("browser", "ok" if rc == 0 else "failed", "" if rc == 0 else "run: uv run tools/hf.py browser ensure")


def step_fonts() -> None:
    d = cfg.path("fonts")
    n = len(list(d.rglob("*.ttf")) + list(d.rglob("*.otf")) + list(d.rglob("*.woff2"))) if d.exists() else 0
    if n >= 20:
        done("fonts", "ok", f"{n} font files")
        return
    if not ask("  Download 17 free Google Fonts families (Devanagari + Latin, OFL, ~40 MB)?"):
        done("fonts", "missing", "uv run tools/fetch_fonts.py")
        return
    rc = run(uv_tool("fetch_fonts.py"))
    done("fonts", "installed" if rc == 0 else "failed")


def step_sfx() -> None:
    idx = ROOT / "library" / "sfx" / "index.json"
    rows = json.loads(idx.read_text(encoding="utf-8")) if idx.exists() else []
    missing = [r for r in rows if not (ROOT / r["file"]).exists()]
    if rows and not missing:
        done("sfx", "ok", f"{len(rows)} effects")
        return
    if A.check:
        done("sfx", "missing", "uv run tools/sfx.py build")
        return
    rc = run(uv_tool("sfx.py", "build"))
    done("sfx", "installed" if rc == 0 else "failed", "synthesised locally (own work, no download)")


def step_luts() -> None:
    cubes = list((ROOT / "library" / "luts").glob("*.cube"))
    if len(cubes) >= 5:
        done("luts", "ok", f"{len(cubes)} looks")
        return
    if A.check:
        done("luts", "missing", "uv run tools/make_luts.py")
        return
    rc = run(uv_tool("make_luts.py"))
    done("luts", "installed" if rc == 0 else "failed")


def step_vision() -> None:
    """Face / person detectors (YuNet MIT, MediaPipe Apache-2.0), < 8 MB total."""
    cache = cfg.path("cache")
    todo = [(t, u, s) for t, u, s in VISION if not ((cache / t).exists() and sha256(cache / t) == s)]
    if not todo:
        done("vision", "ok", "YuNet, BlazeFace, EfficientDet-Lite0")
        return
    if not ask(f"  Download {len(todo)} small face/person detection models (< 8 MB)?"):
        done("vision", "missing", "uv run tools/setup.py --only vision")
        return
    try:
        for t, u, s in todo:
            f = download(u, DL / "vision" / Path(t).name, s)
            (cache / t).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, cache / t)
            with open((cache / t).parent / "SHA256", "a", encoding="utf-8") as fh:
                fh.write(f"{s} *cache/{t}\n")
        done("vision", "installed")
    except Exception as e:  # noqa: BLE001
        done("vision", "failed", str(e))


def install_binary(name: str) -> None:
    b = BINARIES[name]
    d = cfg.path("bin") / name
    exe = d / b["exe"]
    if exe.exists() and sha256(exe) == b["exe_sha"]:
        done(name, "ok", f"bin/{name}/{b['exe']} (SHA-256 ok)")
        return
    if not ask(f"  Download {name} ({b['size_mb']} MB, official GitHub release) for {b['what']}?", default=True):
        done(name, "missing", f"uv run tools/setup.py --only {name}")
        return
    try:
        fname = b["url"].rsplit("/", 1)[1]
        f = download(b["url"], DL / name / fname, b["sha"])
        d.mkdir(parents=True, exist_ok=True)
        if fname.endswith(".zip"):
            with zipfile.ZipFile(f) as z:
                names = z.namelist()
                top = next(n for n in names if n.endswith("/" + b["exe"]) or n == b["exe"])
                prefix = top[: -len(b["exe"])]
                for n in names:
                    if not n.startswith(prefix) or n.endswith("/"):
                        continue
                    rel = n[len(prefix):]
                    if ".." in Path(rel).parts:
                        continue
                    out = d / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(n) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        else:
            shutil.copy2(f, exe)
        if sha256(exe) != b["exe_sha"]:
            raise RuntimeError(f"{exe} hash does not match the recorded release; do not run it")
        (d / "VERSION").write_text(b["version"] + "\n", encoding="utf-8")
        (d / "SHA256").write_text(f"{b['sha']} *{fname}\n{b['exe_sha']} *{b['exe']}\n", encoding="utf-8")
        done(name, "installed", f"bin/{name}/")
    except Exception as e:  # noqa: BLE001
        done(name, "failed", str(e))


def step_auto_editor() -> None:
    exe = ROOT / ".venv" / "Lib" / "site-packages" / "auto_editor" / "bin" / "auto-editor.exe"
    if exe.exists() and sha256(exe) == AUTO_EDITOR_SHA:
        done("auto-editor", "ok", "29.3.1 (SHA-256 matches the GitHub release)")
        return
    if A.check or not ask("  Let auto-editor fetch its official release binary (~30 MB, for silence cutting)?"):
        done("auto-editor", "missing", "uv run auto-editor --version")
        return
    run([str(VENV_BIN / "auto-editor.exe"), "--version"])
    ok = exe.exists() and sha256(exe) == AUTO_EDITOR_SHA
    done("auto-editor", "installed" if ok else "failed", "" if ok else "binary hash differs from the 29.3.1 GitHub digest; do not use fx.py cut-silence")


def step_parakeet() -> None:
    """English speech recognition (NVIDIA Parakeet TDT 0.6B v3 int8, CC-BY-4.0, ~640 MB)."""
    import hf
    p = subprocess.run(hf.hf_cmd() + ["models", "list", "--json"], env=hf.hf_env(), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", cwd=ROOT)
    try:
        m = json.loads(p.stdout[p.stdout.index("{"):])["models"]
        if any(x["engine"] == "parakeet" and x["installed"] for x in m):
            done("parakeet", "ok", "English ASR installed")
            return
    except Exception:  # noqa: BLE001
        pass
    if not ask("  Download Parakeet, the English speech-to-text model (~640 MB)?"):
        done("parakeet", "missing", "uv run tools/hf.py models install parakeet")
        return
    rc = run(uv_tool("hf.py", "models", "install", "parakeet"))
    done("parakeet", "installed" if rc == 0 else "failed")


def step_indic() -> None:
    """Marathi/Hindi speech recognition: Indic-Transcribe (OpenVINO int8) from Hugging Face (gated)."""
    import indic_asr
    from huggingface_hub import HfApi, get_token, snapshot_download
    c = cfg.load().get("indic_asr", {})
    models = sorted({c.get("model_native", "flex"), c.get("model_mixed", "flex")} | ({"core"} if A.with_core else set()))
    need = [m for m in models if not (indic_asr.ov_dir("int8", m) / "decoder.xml").exists()]
    if not need:
        done("indic", "ok", ", ".join(f"Indic-Transcribe-{m.title()} int8" for m in models))
        return
    page = f"https://huggingface.co/{INDIC_REPO}"
    say(f"  Needed: {', '.join(f'Indic-Transcribe-{m.title()}' for m in need)} (~1.2 GB each).\n"
        "  The model is free but gated: you accept its licence once (Indic Open Model License v1.0).\n"
        "    a. Make a free account:   https://huggingface.co/join\n"
        f"    b. Open {page}\n"
        "       fill the short form and click 'Agree and access repository' (approval is automatic)\n"
        "    c. Make a READ token:     https://huggingface.co/settings/tokens  -> Create new token -> Read\n"
        "    d. Log in here (paste the token when asked; it is saved in your user folder, never in this repo)")
    if A.check:
        done("indic", "missing", "uv run tools/setup.py --only indic")
        return
    api = HfApi()
    while True:
        if not get_token():
            if not ask("  Log in to Hugging Face now?"):
                done("indic", "missing", "uv run hf auth login, then uv run tools/setup.py --only indic")
                return
            run([str(VENV_BIN / "hf.exe"), "auth", "login"])
            continue
        try:
            api.auth_check(INDIC_REPO)
            break
        except Exception as e:  # noqa: BLE001
            say(f"  No access yet ({type(e).__name__}). Accept the licence on {page} while logged in as "
                f"the same account as your token.")
            if not ask("  Done? Try again?"):
                done("indic", "missing", f"accept the licence on {page}, then uv run tools/setup.py --only indic")
                return
    if not ask(f"  Download {len(need)} model(s), ~{1.2 * len(need):.1f} GB?"):
        done("indic", "missing", "uv run tools/setup.py --only indic")
        return
    try:
        tmp = cfg.path("cache") / "models" / "_indic_ov_download"
        snapshot_download(INDIC_REPO, local_dir=tmp, allow_patterns=[f"{m}/*" for m in need] + ["LICENSE.md", "README.md"])
        for m in need:
            dest = indic_asr.ov_dir("int8", m)
            if dest.exists():
                shutil.move(str(dest), str(ROOT / "_trash" / f"{dest.name}.old"))
            shutil.move(str(tmp / m), str(dest))
        done("indic", "installed", "Credit line for videos: \"Built with Indic-Transcribe-Flex from Bodhan AI / AI4Bharat.\"")
    except Exception as e:  # noqa: BLE001
        done("indic", "failed", str(e))


def step_models() -> None:
    """Models the tools otherwise download on first use. Fetching them now avoids waiting mid-edit."""
    hub = cfg.path("hf_home") / "hub"
    torch_ck = cfg.path("torch_home") / "hub" / "checkpoints"
    sep_dir = cfg.path("cache") / "audio-separator"
    st = cfg.load().get("stems", {})
    items = [
        ("Beat This! beat tracker (85 MB)", lambda: (torch_ck / "beat_this-final0.ckpt").exists() and (torch_ck / "beat_this-small0.ckpt").exists(),
         _get_beat_this),
        ("CLAP music mood tags (0.8 GB)", lambda: any(hub.glob("models--laion--larger_clap_music_and_speech")), _get_clap),
        ("MMS word-timing aligner (1.2 GB, CC-BY-NC 4.0)", lambda: (hub / "models--MahmoudAshraf--mms-300m-1130-forced-aligner").exists(), _get_mms),
        ("SigLIP 2 footage search (1.5 GB)", lambda: (hub / "models--google--siglip2-base-patch16-224").exists(), _get_siglip),
        ("Stem separation htdemucs + BS-RoFormer (0.7 GB)",
         lambda: all((sep_dir / m).exists() for m in (st.get("fast_model", "htdemucs.yaml"), st.get("quality_model", ""))), _get_separator),
    ]
    todo = [(n, f) for n, have, f in items if not have()]
    if not todo:
        done("models", "ok", "all analysis models cached")
        return
    say("  Not downloaded yet:\n" + "\n".join(f"    - {n}" for n, _ in todo) +
        "\n  (Each one otherwise downloads automatically the first time a tool needs it.)")
    if not ask("  Download them now?"):
        done("models", "skipped", "they download on first use")
        return
    failed = []
    for n, f in todo:
        say(f"  {n} ...")
        try:
            f()
        except Exception as e:  # noqa: BLE001
            failed.append(f"{n}: {e}")
    done("models", "failed" if failed else "installed", "; ".join(failed))


def _get_beat_this() -> None:
    from beat_this.inference import Audio2Beats
    for ck in ("final0", "small0"):
        Audio2Beats(checkpoint_path=ck, device="cpu", dbn=False)


def _get_clap() -> None:
    from transformers import ClapModel, ClapProcessor
    ClapModel.from_pretrained("laion/larger_clap_music_and_speech")
    ClapProcessor.from_pretrained("laion/larger_clap_music_and_speech")


def _get_mms() -> None:
    import align
    align._load()


def _get_siglip() -> None:
    import siglip
    siglip.load()


def _get_separator() -> None:
    import tempfile
    from audio_separator.separator import Separator
    st = cfg.load().get("stems", {})
    with tempfile.TemporaryDirectory() as td:
        sep = Separator(output_dir=td, model_file_dir=str(cfg.path("cache") / "audio-separator"))
        for m in (st.get("fast_model", "htdemucs.yaml"), st.get("quality_model")):
            if m:
                sep.load_model(model_filename=m)


def step_agy() -> None:
    """Optional: Gemini watch-throughs via the Antigravity CLI (needs a Google AI Pro plan)."""
    exe = cfg.agy()
    if exe:
        done("agy", "ok", exe)
        return
    say("  Optional. Gemini reviews (/review --gemini, /perceive) use the Antigravity CLI `agy`,\n"
        "  signed in with a Google account that has Google AI Pro. Without it everything else works,\n"
        "  and perceive.py --relay lets you paste a prompt into the Gemini app by hand.\n"
        "    Install: https://antigravity.google/cli   then run `agy` once and sign in.\n"
        "    NEVER use a Gemini API key with this studio.")
    done("agy", "skipped", "optional")


STEPS = {
    "config": ("FFmpeg / Chrome paths for this computer", step_config),
    "browser": ("HyperFrames render browser", step_browser),
    "fonts": ("Fonts (Devanagari + Latin)", step_fonts),
    "sfx": ("Sound-effects library", step_sfx),
    "luts": ("Colour looks (LUTs)", step_luts),
    "vision": ("Face / person detection models", step_vision),
    "rife": ("RIFE slow motion", lambda: install_binary("rife")),
    "realesrgan": ("Real-ESRGAN upscaler", lambda: install_binary("realesrgan")),
    "deepfilter": ("DeepFilterNet voice cleanup", lambda: install_binary("deepfilter")),
    "auto-editor": ("auto-editor (silence cutting)", step_auto_editor),
    "parakeet": ("English speech-to-text (Parakeet)", step_parakeet),
    "indic": ("Marathi / Hindi speech-to-text (Indic-Transcribe)", step_indic),
    "models": ("Analysis models (beats, mood, alignment, search, stems)", step_models),
    "agy": ("Gemini via Antigravity (optional)", step_agy),
}


def main() -> int:
    global A
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="only report, change nothing")
    ap.add_argument("--yes", action="store_true", help="answer yes to every download")
    ap.add_argument("--only", help="comma-separated steps: " + ",".join(STEPS))
    ap.add_argument("--with-core", action="store_true", help="also download Indic-Transcribe-Core (not needed by default)")
    A = ap.parse_args()
    if sys.version_info[:2] != (3, 11) or ".venv" not in sys.prefix:
        say("Run this through uv from the studio folder:  uv run tools/setup.py")
        return 2
    names = [s.strip() for s in A.only.split(",")] if A.only else list(STEPS)
    bad = [n for n in names if n not in STEPS]
    if bad:
        say(f"unknown step(s) {bad}; choose from {list(STEPS)}")
        return 2
    for i, n in enumerate(names, 1):
        title, fn = STEPS[n]
        head(i, len(names), title)
        try:
            fn()
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            done(n, "failed", f"{type(e).__name__}: {e}")
    say("\n=== Summary " + "=" * 50)
    for step, status, note in RESULTS:
        say(f"  {status.upper():10s} {step:12s} {note}")
    bad = [r for r in RESULTS if r[1] in ("failed", "missing") and r[0] not in ("agy",)]
    say("\nAll set. Next: uv run tools/doctor.py" if not bad else
        "\nSome steps still need you (see above). Re-run any time: uv run tools/setup.py")
    return 1 if any(r[1] == "failed" for r in RESULTS) else 0


if __name__ == "__main__":
    sys.exit(main())

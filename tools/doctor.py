"""Studio health check: every tool, path, model and login the workflow needs.

Usage:  uv run tools/doctor.py [--phase N] [--json]

Each check belongs to a build phase. Checks for phases not built yet show as
"pending" instead of failing. Extend CHECKS every phase.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

# Highest phase that has been built. Checks above it are "pending".
BUILT_PHASE = 13


@dataclass
class Result:
    ok: bool
    detail: str
    fix: str = ""


@dataclass
class Check:
    phase: int
    name: str
    fn: Callable[[], Result]
    optional: bool = False


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, shell=False)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def npx(*args: str) -> list[str]:
    exe = shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    return [exe, "--no-install", *args]


# ---------------------------------------------------------------- phase 0

def chk_python() -> Result:
    v = sys.version_info
    ok = (v.major, v.minor) == (3, 11) and ".venv" in sys.prefix
    return Result(ok, f"{sys.version.split()[0]} ({sys.prefix})",
                  "run via `uv run tools/doctor.py`")


def chk_libs(mods: list[str]) -> Callable[[], Result]:
    def f() -> Result:
        missing, vers = [], []
        for m in mods:
            try:
                mod = importlib.import_module(m)
                vers.append(f"{m} {getattr(mod, '__version__', '?')}")
            except Exception:
                missing.append(m)
        if missing:
            return Result(False, "missing: " + ", ".join(missing), "uv sync")
        return Result(True, ", ".join(vers))
    return f


def chk_ffmpeg() -> Result:
    exe = cfg.ffmpeg()
    if not Path(exe).exists():
        return Result(False, f"not found: {exe}", "run installation.bat (winget Gyan.FFmpeg) or set [paths].ffmpeg in config/studio.local.toml")
    _, out = run([exe, "-hide_banner", "-version"])
    ver = out.splitlines()[0].split(" Copyright")[0] if out else "?"
    _, filt = run([exe, "-hide_banner", "-filters"])
    need = ["drawtext", "lut3d", "vidstabdetect", "vidstabtransform", "minterpolate",
            "ebur128", "loudnorm", "blackdetect", "freezedetect"]
    missing = [n for n in need if not re.search(rf"\s{n}\s", filt)]
    if missing:
        return Result(False, f"{ver}; missing filters: {missing}", "use the Gyan full build")
    return Result(True, f"{ver}; filters OK")


def chk_ffprobe() -> Result:
    exe = cfg.ffprobe()
    rc, out = run([exe, "-hide_banner", "-version"])
    return Result(rc == 0, out.splitlines()[0].split(" Copyright")[0] if rc == 0 else exe)


def chk_chrome() -> Result:
    p = cfg.path("chrome")
    return Result(p.exists(), str(p), "install Google Chrome or set [paths].chrome in config/studio.local.toml")


def chk_node() -> Result:
    rc, out = run(["node", "--version"])
    if rc:
        return Result(False, "node not found", "install Node >= 22")
    major = int(out.lstrip("v").split(".")[0])
    return Result(major >= 22, out, "HyperFrames needs Node >= 22")


def chk_uv() -> Result:
    exe = shutil.which("uv") or str(Path.home() / ".local/bin/uv.exe")
    rc, out = run([exe, "--version"])
    return Result(rc == 0, out)


def chk_git() -> Result:
    rc, out = run(["git", "-C", str(cfg.ROOT), "rev-parse", "--is-inside-work-tree"])
    return Result(rc == 0 and out == "true", "repo initialised" if rc == 0 else out, "git init")


def chk_docker() -> Result:
    rc, out = run(["docker", "--version"])
    return Result(rc == 0, out if rc == 0 else "not installed")


def chk_disk() -> Result:
    free = shutil.disk_usage(cfg.ROOT).free / 1e9
    return Result(free > 20, f"{free:.0f} GB free on {cfg.ROOT.drive}", "free up disk space")


def chk_config() -> Result:
    try:
        cfg.load("studio")
        cfg.load("export_presets")
        return Result(True, "studio.toml + export_presets.toml parse")
    except Exception as e:  # noqa: BLE001
        return Result(False, str(e))


def chk_secrets() -> Result:
    if (cfg.ROOT / ".env").exists():
        rc, out = run(["git", "-C", str(cfg.ROOT), "check-ignore", ".env"])
        if rc != 0:
            return Result(False, ".env exists and is NOT git-ignored", "add .env to .gitignore")
    if os.environ.get("GEMINI_API_KEY"):
        return Result(False, "GEMINI_API_KEY is set (leaked key; not used by the studio)",
                      "revoke it in AI Studio and delete the user env var")
    return Result(True, "no tracked secrets; GEMINI_API_KEY unset")


# ---------------------------------------------------------------- phase 1

def chk_hf_cli() -> Result:
    rc, out = run(npx("hyperframes", "--version"), timeout=120)
    if rc:
        return Result(False, out[-200:], "npm install")
    return Result(True, f"hyperframes {out.splitlines()[-1]}")


def chk_hf_skills() -> Result:
    d = cfg.ROOT / ".claude" / "skills"
    names = sorted(p.name for p in d.iterdir() if (p / "SKILL.md").exists()) if d.exists() else []
    hf = [n for n in names if "hyperframes" in n or n in {"gsap", "music-to-video"}]
    return Result(bool(hf), ", ".join(names) or "none",
                  "npx skills add heygen-com/hyperframes")


def chk_hf_fonts() -> Result:
    d = cfg.path("fonts")
    fonts = list(d.rglob("*.ttf")) + list(d.rglob("*.woff2")) + list(d.rglob("*.otf"))
    deva = [f for f in fonts if "devanagari" in f.name.lower() or "mukta" in f.name.lower()]
    return Result(bool(deva), f"{len(fonts)} font files, {len(deva)} Devanagari",
                  "download Noto Sans Devanagari + Mukta into library/fonts/")


# ---------------------------------------------------------------- phase 2

def chk_beat_this() -> Result:
    ck = cfg.path("torch_home") / "hub" / "checkpoints"
    have = sorted(p.name for p in ck.glob("beat_this-*.ckpt")) if ck.exists() else []
    try:
        importlib.import_module("beat_this.inference")
    except Exception as e:  # noqa: BLE001
        return Result(False, f"import failed: {e}", "uv sync")
    ok = "beat_this-final0.ckpt" in have
    return Result(ok, ", ".join(have) or "no checkpoints",
                  "run any analysis once: uv run tools/analyze_audio.py tests/fixtures/beat_128.wav")


def chk_clap() -> Result:
    hub = cfg.path("hf_home") / "hub"
    have = [d.name for d in hub.glob("models--laion--*clap*")] if hub.exists() else []
    return Result(bool(have), ", ".join(have) or "not downloaded",
                  "first analyze_audio.py run without --no-tags downloads it (~0.8 GB)")


def chk_separator() -> Result:
    d = cfg.path("cache") / "audio-separator"
    s = cfg.load().get("stems", {})
    want = [s.get("fast_model", "htdemucs.yaml"), s.get("quality_model", "")]
    have = {p.name for p in d.iterdir()} if d.exists() else set()
    missing = [m for m in want if m and m not in have]
    try:
        importlib.import_module("audio_separator.separator")
    except Exception as e:  # noqa: BLE001
        return Result(False, f"import failed: {e}", "uv sync")
    return Result(not missing, "models: " + ", ".join(m for m in want if m in have) +
                  (f"; missing {missing}" if missing else ""),
                  "uv run tools/separate.py tests/fixtures/vocalmix.wav [--quality]")


# ---------------------------------------------------------------- phase 3

def chk_aligner() -> Result:
    hub = cfg.path("hf_home") / "hub" / "models--MahmoudAshraf--mms-300m-1130-forced-aligner"
    try:
        importlib.import_module("ctc_forced_aligner")
    except Exception as e:  # noqa: BLE001
        return Result(False, f"import failed: {e}", "uv sync")
    return Result(hub.exists(), "MMS-300m aligner cached" if hub.exists() else "model not downloaded",
                  "uv run tests/eval_align.py  (downloads ~1.2 GB once)")


def chk_parakeet() -> Result:
    rc, out = run(npx("hyperframes", "models", "list", "--json"), timeout=120)
    try:
        m = json.loads(out[out.index("{"):])["models"]
        ok = any(x["engine"] == "parakeet" and x["installed"] for x in m)
    except Exception:  # noqa: BLE001
        return Result(False, out[-200:], "uv run tools/hf.py models install parakeet")
    return Result(ok, "parakeet-tdt-0.6b-v3 installed" if ok else "not installed",
                  "uv run tools/hf.py models install parakeet")


def chk_indic_asr() -> Result:
    m = cfg.path("cache") / "models"
    want = cfg.load().get("indic_asr", {}).get("model_mixed", "flex")
    ov_ok = all((m / f"indic-transcribe-{want}-ov-int8" / f).exists() for f in ("encoder.xml", "cross_kv.xml", "decoder.xml"))
    ref = (m / f"indic-transcribe-{want}" / "model.safetensors").exists()
    try:
        import openvino  # noqa: F401
        import sentencepiece  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return Result(False, f"import failed: {e}", "uv sync")
    detail = (f"{want}: OpenVINO int8 IR ready" if ov_ok else f"{want}: OpenVINO IR missing") + \
        ("; official fp32 reference present" if ref else "; official checkpoint not downloaded")
    return Result(ov_ok, detail, "uv run tools/setup.py --only indic (HF login + licence, see SETUP.md step 6)")


# ---------------------------------------------------------------- phase 4

def chk_vision_models() -> Result:
    import cv2
    need = {"YuNet": cfg.path("cache") / "opencv" / "face_detection_yunet_2023mar.onnx",
            "EfficientDet-Lite0": cfg.path("cache") / "mediapipe" / "efficientdet_lite0.tflite"}
    missing = [k for k, p in need.items() if not p.exists()]
    if missing:
        return Result(False, f"missing: {missing}", "uv run tools/setup.py --only vision")
    return Result(hasattr(cv2, "saliency"), "YuNet, EfficientDet-Lite0, cv2.saliency",
                  "opencv-contrib-python must be installed last (uv sync --reinstall-package opencv-contrib-python)")


def chk_siglip() -> Result:
    hub = cfg.path("hf_home") / "hub" / "models--google--siglip2-base-patch16-224"
    return Result(hub.exists(), "siglip2-base-patch16-224 cached" if hub.exists() else "not downloaded",
                  "uv run tools/index_footage.py <clip>  (downloads ~1.5 GB once)")


# ---------------------------------------------------------------- later phases

def chk_agy() -> Result:
    exe = cfg.agy()
    if not exe:
        return Result(False, "agy CLI not installed (optional: Gemini reviews)", "see SETUP.md, step 8")
    rc, ver = run([exe, "--version"])
    rc2, models = run([exe, "models"], timeout=90)
    want = cfg.load().get("gemini", {}).get("model", "gemini-3.8-flash-high")
    if rc2 != 0 or want not in models:
        return Result(False, f"agy {ver}; model {want} not listed (signed in?)",
                      "run `agy` once in a terminal and sign in with your Google account (⛔ USER)")
    return Result(True, f"agy {ver}; {want} available")


def chk_hf_login() -> Result:
    cands = [Path(os.environ["HF_TOKEN_PATH"])] if os.environ.get("HF_TOKEN_PATH") else []
    cands += [Path.home() / ".cache" / "huggingface" / "token", cfg.path("hf_home") / "token"]
    tok = next((c for c in cands if c.exists()), None)
    if os.environ.get("HF_TOKEN"):
        return Result(True, "HF_TOKEN set in environment")
    return Result(tok is not None, f"token at {tok}" if tok else "not logged in",
                  "user runs `uv run hf auth login` (⛔ USER)")


def chk_bin(name: str) -> Callable[[], Result]:
    """Vendored binary present, and its SHA-256 still matches bin/<name>/SHA256."""
    def f() -> Result:
        import hashlib
        d = cfg.path("bin") / name
        exes = list(d.glob("*.exe")) if d.exists() else []
        if not exes:
            return Result(False, f"{d} empty", f"uv run tools/setup.py --only {name}")
        rec = {}
        if (d / "SHA256").exists():
            for line in (d / "SHA256").read_text(encoding="utf-8").splitlines():
                h, _, fn = line.partition(" ")
                rec[fn.lstrip("*").strip()] = h
        bad = [e.name for e in exes if e.name in rec and
               hashlib.sha256(e.read_bytes()).hexdigest() != rec[e.name]]
        unrec = [e.name for e in exes if e.name not in rec]
        ver = (d / "VERSION").read_text(encoding="utf-8").splitlines()[0] if (d / "VERSION").exists() else "?"
        if bad:
            return Result(False, f"SHA-256 MISMATCH: {bad}", "re-download the official release; do not run it")
        return Result(not unrec, f"{ver}; sha256 ok" + (f"; unrecorded {unrec}" if unrec else ""),
                      f"record hashes in bin/{name}/SHA256")
    return f


def chk_auto_editor() -> Result:
    import hashlib
    exe = cfg.ROOT / ".venv" / "Lib" / "site-packages" / "auto_editor" / "bin" / "auto-editor.exe"
    want = "ba8eecd647355359436b7088d61ffa7a9ea07a88dc121b999cc337b882400c05"  # GitHub digest, 29.3.1
    if not exe.exists():
        return Result(False, "binary not downloaded yet", "uv run auto-editor --version (fetches the official release)")
    h = hashlib.sha256(exe.read_bytes()).hexdigest()
    return Result(h == want, "29.3.1, sha256 matches the GitHub release digest" if h == want else f"sha256 {h[:12]}… (expected {want[:12]}…)",
                  "uv sync --reinstall-package auto-editor, then re-check the release digest")


def chk_luts() -> Result:
    d = cfg.ROOT / "library" / "luts"
    cubes = sorted(p.stem for p in d.glob("*.cube"))
    return Result(bool(cubes), ", ".join(cubes) or "none", "uv run tools/make_luts.py")


def chk_music_lib() -> Result:
    p = cfg.ROOT / "library" / "music" / "index.json"
    rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    missing = [r["title"] for r in rows if not (cfg.ROOT / r["file"]).exists()]
    if missing:
        return Result(False, f"{len(rows)} tracks; files missing: {missing[:3]}",
                      "re-download the tracks or remove them from the index")
    return Result(len(rows) >= 3, f"{len(rows)} tracks indexed", "uv run tools/music_library.py add <file> --preset incompetech")


def chk_sfx_lib() -> Result:
    p = cfg.ROOT / "library" / "sfx" / "index.json"
    rows = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
    ok = [r for r in rows if (cfg.ROOT / r["file"]).exists()]
    return Result(len(ok) >= 10 and len(ok) == len(rows), f"{len(ok)}/{len(rows)} effects present",
                  "uv run tools/sfx.py build")


def chk_brands() -> Result:
    import brand
    kits = sorted(d.name for d in brand.BRANDS.iterdir() if (d / "brand.json").exists()) if brand.BRANDS.exists() else []
    issues = {k: brand.check(brand.load(k)) for k in kits}
    bad = {k: v for k, v in issues.items() if v}
    if bad:
        return Result(False, "; ".join(f"{k}: {v[0]}" for k, v in bad.items()), "uv run tools/brand.py check <brand>")
    todo = {k: len(brand.load(k).get("to_confirm", [])) for k in kits}
    return Result(bool(kits), ", ".join(f"{k} ({n} facts to confirm)" if n else k for k, n in todo.items()) or "none",
                  "uv run tools/brand.py new <brand>")


def chk_stock_keys() -> Result:
    have = [k for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY") if os.environ.get(k)]
    missing = [k for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY") if k not in have]
    return Result(not missing, ("keys set: " + ", ".join(have) if have else "no keys") +
                  "; Openverse + Commons always available",
                  "⛔ USER: free keys from pexels.com/api and pixabay.com/api/docs → user env vars " + ", ".join(missing))


def chk_vendor() -> Result:
    """GSAP + HyperFrames shader-transitions copied into every built project (no CDN at render time)."""
    import hashlib
    d = cfg.ROOT / "library" / "vendor"
    rows = []
    for sub in ("gsap-3.14.2", "shader-transitions-0.8.172"):
        sha = d / sub / "SHA256"
        if not sha.exists():
            return Result(False, f"{sub} missing", "see library/vendor/README.md")
        h, _, fn = sha.read_text(encoding="utf-8").strip().partition(" ")
        f = d / sub / fn.lstrip("*").strip()
        if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != h:
            return Result(False, f"{sub}: SHA-256 mismatch", "re-fetch the official npm package (library/vendor/README.md)")
        rows.append(sub)
    return Result(True, ", ".join(rows) + "; sha256 ok")


def chk_build_tools() -> Result:
    import importlib
    mods = ["edl", "snap", "prep", "mix", "build", "fonts", "audiomap", "new_video", "ingest"]
    for m in mods:
        importlib.import_module(m)
    recipes = sorted(p.stem for p in (cfg.ROOT / "docs" / "recipes").glob("*.md") if p.stem != "README")
    return Result(len(recipes) >= 13, f"{len(mods)} modules import; {len(recipes)} recipes", "docs/recipes/")


def chk_review() -> Result:
    import importlib
    importlib.import_module("review")
    importlib.import_module("fontTools.ttLib")
    js = cfg.ROOT / "tools" / "js" / "measure_text.mjs"
    pp = cfg.ROOT / "node_modules" / "puppeteer-core"
    ok = js.exists() and pp.exists()
    return Result(ok, "review.py, fontTools, puppeteer-core + measure_text.mjs" if ok else "measure script or puppeteer-core missing",
                  "npm install (puppeteer-core comes with hyperframes)")


def chk_export() -> Result:
    import export
    p = export.presets()
    need = {"reels", "shorts", "feed45", "square", "youtube", "whatsapp", "master"}
    miss = sorted(need - set(p))
    return Result(not miss, f"{len(p)} presets: {', '.join(sorted(p))}" if not miss else f"missing presets {miss}",
                  "config/export_presets.toml")


def chk_commands() -> Result:
    want = {"doctor", "new-video", "ingest", "analyze", "perceive", "plan", "build", "review", "export", "music",
            "stock", "brand", "credits"}
    have = {p.stem for p in (cfg.ROOT / ".claude" / "commands").glob("*.md")}
    skill = (cfg.ROOT / ".claude" / "skills" / "studio" / "SKILL.md").exists()
    miss = sorted(want - have)
    return Result(not miss and skill, f"{len(have & want)}/13 commands, studio skill {'ok' if skill else 'missing'}"
                  + (f"; missing {miss}" if miss else ""), ".claude/commands, .claude/skills/studio")


CHECKS: list[Check] = [
    Check(0, "python (.venv 3.11)", chk_python),
    Check(0, "python base libs", chk_libs(["numpy", "scipy", "cv2", "PIL", "soundfile",
                                            "librosa", "tqdm", "pydantic", "rich", "tomli_w"])),
    Check(0, "config files", chk_config),
    Check(0, "ffmpeg (pinned full build)", chk_ffmpeg),
    Check(0, "ffprobe", chk_ffprobe),
    Check(0, "chrome", chk_chrome),
    Check(0, "node >= 22", chk_node),
    Check(0, "uv", chk_uv),
    Check(0, "git repo", chk_git),
    Check(0, "disk space", chk_disk),
    Check(0, "secrets hygiene (⛔ USER)", chk_secrets, optional=True),
    Check(0, "docker", chk_docker, optional=True),
    Check(1, "hyperframes CLI (pinned)", chk_hf_cli),
    Check(1, "hyperframes skills", chk_hf_skills),
    Check(1, "fonts (Devanagari)", chk_hf_fonts),
    Check(2, "python audio libs", chk_libs(["torch", "beat_this", "transformers", "audio_separator",
                                            "edge_tts", "matplotlib"])),
    Check(2, "Beat This! weights", chk_beat_this),
    Check(2, "CLAP model", chk_clap),
    Check(2, "audio-separator models", chk_separator),
    Check(3, "MMS forced aligner", chk_aligner),
    Check(3, "Parakeet English ASR", chk_parakeet),
    Check(3, "hugging face login (⛔ USER)", chk_hf_login, optional=True),
    Check(3, "Indic-Transcribe-Flex (OpenVINO int8)", chk_indic_asr),
    Check(4, "python footage libs", chk_libs(["scenedetect", "mediapipe", "imagehash", "cv2"])),
    Check(4, "face/person/saliency models", chk_vision_models),
    Check(4, "SigLIP 2 search model", chk_siglip),
    Check(5, "Antigravity CLI (agy) + Gemini 3.8 Flash", chk_agy, optional=True),
    Check(6, "RIFE (bin/rife)", chk_bin("rife")),
    Check(6, "Real-ESRGAN (bin/realesrgan)", chk_bin("realesrgan")),
    Check(6, "DeepFilterNet (bin/deepfilter)", chk_bin("deepfilter")),
    Check(6, "auto-editor", chk_auto_editor),
    Check(6, "colour LUTs", chk_luts),
    Check(8, "music library", chk_music_lib),
    Check(8, "SFX library", chk_sfx_lib),
    Check(8, "brand kits", chk_brands),
    Check(8, "Pexels/Pixabay keys (⛔ USER)", chk_stock_keys, optional=True),
    Check(9, "vendored GSAP + shader-transitions", chk_vendor),
    Check(9, "build layer (EDL, snap, prep, mix, build)", chk_build_tools),
    Check(10, "review / QA", chk_review),
    Check(11, "export presets", chk_export),
    Check(12, "slash commands + studio skill", chk_commands),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phase", type=int, default=BUILT_PHASE, help="treat phases <= N as required")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args()

    rows = []
    for c in CHECKS:
        try:
            r = c.fn()
        except Exception as e:  # noqa: BLE001
            r = Result(False, f"error: {e}")
        if r.ok:
            status = "ok"
        elif c.phase > a.phase:
            status = "pending"
        elif c.optional:
            status = "warn"
        else:
            status = "FAIL"
        rows.append({"phase": c.phase, "check": c.name, "status": status,
                     "detail": r.detail, "fix": "" if r.ok else r.fix})

    if a.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        from rich.console import Console
        from rich.table import Table
        colour = {"ok": "green", "pending": "yellow", "warn": "yellow", "FAIL": "bold red"}
        t = Table(title=f"Studio doctor (required up to phase {a.phase})")
        for col in ("Ph", "Check", "Status", "Detail", "Fix"):
            t.add_column(col, overflow="fold")
        for r in rows:
            t.add_row(str(r["phase"]), r["check"], f"[{colour[r['status']]}]{r['status']}[/]",
                      r["detail"], r["fix"])
        Console(width=max(Console().width, 150)).print(t)
    return 1 if any(r["status"] == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())

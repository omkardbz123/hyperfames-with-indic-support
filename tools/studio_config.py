"""Shared helpers: load config/studio.toml (+ this computer's studio.local.toml) and make Windows stdout UTF-8 safe."""
from __future__ import annotations

import os
import shutil
import sys
import tomllib
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / "config" / "studio.local.toml"   # machine-specific overrides (git-ignored)


def utf8_stdout() -> None:
    """Non-ASCII titles crash cp1252 consoles on Windows; force UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@lru_cache(maxsize=None)
def load(name: str = "studio") -> dict:
    with open(ROOT / "config" / f"{name}.toml", "rb") as f:
        d = tomllib.load(f)
    if name == "studio" and LOCAL.exists():
        with open(LOCAL, "rb") as f:
            d = _merge(d, tomllib.load(f))
    return d


def model_cache_env() -> None:
    """Keep model downloads inside cache/ (call before importing torch/transformers)."""
    os.environ.setdefault("HF_HOME", str(path("hf_home")))
    os.environ.setdefault("TORCH_HOME", str(path("torch_home")))
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    # `hf auth login` (run by the user without our HF_HOME) saves the token in the default
    # place; read it from there so gated models (Indic-Transcribe) work with our cache.
    os.environ.setdefault("HF_TOKEN_PATH", str(Path.home() / ".cache" / "huggingface" / "token"))


def path(key: str) -> Path:
    """A [paths] entry; relative values are inside the studio folder, "auto" is detected."""
    v = str(load()["paths"].get(key, "auto"))
    if v == "auto":
        return Path(_detect(key))
    p = Path(os.path.expandvars(v))
    return p if p.is_absolute() else ROOT / p


def _winget_ffmpeg_full(exe: str) -> str | None:
    pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    hits = sorted(pkgs.glob(f"Gyan.FFmpeg_*/ffmpeg-*-full_build/bin/{exe}")) if pkgs.exists() else []
    return str(hits[-1]) if hits else None


@lru_cache(maxsize=None)
def _detect(key: str) -> str:
    if key in ("ffmpeg", "ffprobe"):
        exe = f"{key}.exe" if os.name == "nt" else key
        for c in (ROOT / "bin" / "ffmpeg" / "bin" / exe, ROOT / "bin" / "ffmpeg" / exe):
            if c.exists():
                return str(c)
        return _winget_ffmpeg_full(exe) or shutil.which(key) or key
    if key == "chrome":
        for base in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if base and (c := Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe").exists():
                return str(c)
        return shutil.which("chrome") or shutil.which("google-chrome") or "chrome.exe"
    raise KeyError(f"[paths].{key} is 'auto' but has no detector; set it in config/studio.local.toml")


def agy() -> str | None:
    """The Antigravity CLI, if installed."""
    v = load().get("gemini", {}).get("agy_path", "auto")
    for c in ([] if v in ("", "auto") else [v]) + [shutil.which("agy") or "",
                                                  str(Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe")]:
        if c and Path(c).exists():
            return c
    return None


def ffmpeg() -> str:
    return str(path("ffmpeg"))


def ffprobe() -> str:
    return str(path("ffprobe"))

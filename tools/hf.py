"""Run the pinned HyperFrames CLI with the studio's environment.

Usage:  uv run tools/hf.py <hyperframes args...>
        e.g. uv run tools/hf.py render -o out.mp4      (run from inside a project folder)

Sets:
  HYPERFRAMES_FFMPEG_PATH / HYPERFRAMES_FFPROBE_PATH  -> the pinned Gyan full build
                                                         (PATH order would pick choco "essentials")
  HYPERFRAMES_PYTHON          -> this repo's .venv python
  HYPERFRAMES_NO_TELEMETRY=1  -> no usage telemetry
  strips cloud API keys (see BLOCKED_ENV) so no skill silently uses a paid/limited API
  render tuning from [render] in config/studio.toml (workers, parallel stream)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402


# Cloud/paid credentials some HyperFrames skills auto-detect (Lyria via the Gemini API,
# HeyGen, ElevenLabs, OpenRouter). The studio is free-only and never uses the Gemini API,
# so strip them from the child environment.
BLOCKED_ENV = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY", "HEYGEN_API_KEY",
               "HEYGEN_ACCESS_TOKEN", "HYPERFRAMES_API_KEY", "ELEVENLABS_API_KEY",
               "OPENROUTER_API_KEY", "OPENAI_API_KEY", "HYPERFRAMES_VERTEX_SERVICE_ACCOUNT")


def hf_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k.upper() not in BLOCKED_ENV}
    env["HYPERFRAMES_FFMPEG_PATH"] = cfg.ffmpeg()
    env["HYPERFRAMES_FFPROBE_PATH"] = cfg.ffprobe()
    env["HYPERFRAMES_PYTHON"] = sys.executable
    # `hyperframes audio`/`beats` use Beat This! from this venv instead of the signal fallback.
    env["HYPERFRAMES_BEAT_THIS_PYTHON"] = sys.executable
    env["HYPERFRAMES_NO_TELEMETRY"] = "1"
    # Skills are managed project-locally in .claude/skills (npx skills add); stop `init`
    # from installing them into every AI tool on the machine.
    env.setdefault("HYPERFRAMES_SKIP_SKILLS", "1")
    env.setdefault("HF_HOME", str(cfg.path("hf_home")))
    env.setdefault("TORCH_HOME", str(cfg.path("torch_home")))  # Beat This! weights live here
    # Keep the extracted-frame cache on D: (C: temp can fill up on long renders).
    env.setdefault("HYPERFRAMES_EXTRACT_CACHE_DIR", str(cfg.path("cache") / "hf-frames"))
    r = cfg.load().get("render", {})
    # Multi-worker screenshot capture streams to the encoder instead of disk (Windows).
    if "parallel_stream" in r:
        env.setdefault("HF_CAPTURE_PARALLEL_STREAM", "true" if r["parallel_stream"] else "false")
    for k, v in r.get("env", {}).items():
        env[k] = str(v)
    return env


def hf_cmd() -> list[str]:
    bin_dir = cfg.ROOT / "node_modules" / ".bin"
    exe = bin_dir / ("hyperframes.cmd" if os.name == "nt" else "hyperframes")
    if not exe.exists():
        sys.exit(f"HyperFrames CLI not installed at {exe}; run `npm install` in {cfg.ROOT}")
    return [str(exe)]


def with_defaults(args: list[str]) -> list[str]:
    """Add the benchmarked worker count to `render` unless the caller chose one."""
    args = list(args)
    workers = cfg.load().get("render", {}).get("workers", 0)
    if args[:1] == ["render"] and workers and not any(
            a in ("-w", "--workers") or a.startswith("--workers=") for a in args):
        args[1:1] = ["-w", str(workers)]
    return args


def run(args: list[str], cwd: str | Path | None = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(hf_cmd() + with_defaults(args), env=hf_env(), cwd=cwd, check=check)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]).returncode)

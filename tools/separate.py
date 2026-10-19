"""Separate an audio/video file into stems with audio-separator; cache per asset.

Usage:  uv run tools/separate.py <file> [--quality] [--model NAME] [--fresh]

  default   : htdemucs -> vocals, drums, bass, other + instrumental (= drums+bass+other)
              ~1x real time on CPU; vocals SDR 28 dB on the fixture
  --quality : BS-RoFormer -> vocals + instrumental
              ~8x real time on CPU; vocals SDR 32 dB; use for lyric alignment on real songs
Models are set in [stems] of config/studio.toml.

Stems land in analysis/<asset-id>/stems/<model>/<stem>.wav (44.1 kHz stereo); stems/stems.json
records model, device, timing. Models download once into cache/audio-separator/.
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()
cfg.model_cache_env()

import assets  # noqa: E402
import audiolib as al  # noqa: E402

DEFAULTS = {"fast_model": "htdemucs.yaml", "quality_model": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "mdxc_overlap": None, "demucs_shifts": 2}


def settings() -> dict:
    return {**DEFAULTS, **cfg.load().get("stems", {})}


def _norm(name: str) -> str:
    """'(Vocals)' / 'No Vocals' / 'Instrumental' -> canonical lower-case stem name."""
    n = name.lower().strip("() ")
    return {"no vocals": "instrumental", "no_vocals": "instrumental"}.get(n, n)


def separate(path: str | Path, quality: bool = False, model: str | None = None, fresh: bool = False,
             quiet: bool = False) -> dict[str, Path]:
    path = Path(path)
    st = settings()
    model = model or st["quality_model" if quality else "fast_model"]
    out_dir = assets.analysis_dir(path) / "stems"
    meta_p = out_dir / "stems.json"
    meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {"runs": {}}
    run = meta["runs"].get(model)
    if run and not fresh and all(Path(p).exists() for p in run["stems"].values()):
        if not quiet:
            print(f"cached stems ({model}): {Path(next(iter(run['stems'].values()))).parent}")
        return {k: Path(v) for k, v in run["stems"].items()}

    from audio_separator.separator import Separator
    run_dir = out_dir / assets.sanitise(Path(model).stem, 60)   # one folder per model
    tmp = out_dir / f"_tmp_{int(time.time())}"
    run_dir.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    sep = Separator(output_dir=str(tmp), model_file_dir=str(cfg.path("cache") / "audio-separator"),
                    output_format="WAV", sample_rate=44100,
                    log_level=logging.WARNING if quiet else logging.INFO,
                    mdxc_params={"segment_size": 256, "override_model_segment_size": False,
                                 "batch_size": 1, "overlap": st["mdxc_overlap"], "pitch_shift": 0},
                    demucs_params={"segment_size": "Default", "shifts": st["demucs_shifts"],
                                   "overlap": 0.25, "segments_enabled": True})
    t0 = time.time()
    sep.load_model(model_filename=model)
    files = sep.separate(str(path))
    elapsed = time.time() - t0
    stems: dict[str, Path] = {}
    for f in files:
        f = Path(f) if Path(f).is_absolute() else tmp / f
        # audio-separator names outputs "<input>_(Vocals)_<model>.wav"
        stem = _norm(f.stem.split("_(")[-1].split(")")[0]) if "_(" in f.stem else _norm(f.stem)
        dest = run_dir / f"{stem}.wav"
        shutil.move(str(f), dest)
        stems[stem] = dest
    try:
        tmp.rmdir()  # ours, and empty after the moves
    except OSError:
        pass
    if "instrumental" not in stems and {"drums", "bass", "other"} <= stems.keys():
        parts = [al.decode(stems[k], 44100, 2) for k in ("drums", "bass", "other")]
        n = min(len(p) for p in parts)
        stems["instrumental"] = al.write_wav(run_dir / "instrumental.wav", sum(p[:n] for p in parts), 44100)
    dur = len(al.decode_mono(path, 8000)) / 8000
    meta["runs"][model] = {"stems": {k: str(v) for k, v in sorted(stems.items())}, "seconds": round(elapsed, 1),
                           "audio_seconds": round(dur, 1), "rtf": round(elapsed / max(dur, 1e-6), 2),
                           "device": "cpu", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    meta_p.write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if not quiet:
        print(f"{model}: {sorted(stems)} in {elapsed:.1f} s (RTF {elapsed / max(dur, 1e-6):.2f}, cpu)")
    return stems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", type=Path)
    ap.add_argument("--quality", action="store_true", help="BS-RoFormer vocals/instrumental (slow, best vocals)")
    ap.add_argument("--model", help="any audio-separator model filename (overrides config)")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if not a.file.exists():
        sys.exit(f"not found: {a.file}")
    stems = separate(a.file, quality=a.quality, model=a.model, fresh=a.fresh, quiet=a.quiet)
    for k, v in sorted(stems.items()):
        print(f"  {k:<13} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

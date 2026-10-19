"""Footage processing toolkit: one CLI over ffmpeg, RIFE, Real-ESRGAN, auto-editor, deep-filter.

Usage:  uv run tools/fx.py <command> <in> <out> [options]      (uv run tools/fx.py <command> -h)

  slowmo      RIFE frame interpolation (Intel Arc via Vulkan): --factor 4 [--start s --end s]
              [--model rife-v4.6] [--keep-fps]  (default: play the new frames at the source fps,
              i.e. real slow motion; --keep-fps renders at fps x factor = smooth, same speed)
              --engine minterpolate uses ffmpeg instead (fallback)
  upscale     Real-ESRGAN: images (default realesrgan-x4plus, best detail, ~13 s/frame) or video
              (default realesr-animevideov3, ~0.4 s/frame); --height 1080 final size (lanczos)
  stabilize   ffmpeg vidstab two-pass: --smoothing 30 --zoom 0 (adaptive zoom hides borders)
  cut-silence auto-editor: drop silences/dead air. --threshold 4% --margin 0.2s
  denoise-voice  80 Hz high-pass + DeepFilterNet3 (deep-filter); video stream copied. --atten 100
  speed       constant speed change with pitch-kept audio: --factor 2 (fast) / 0.5 (slow)
  lut         apply a .cube LUT: --lut library/luts/x.cube [--mix 1.0]
  key         chroma key to transparent ProRes/WebM: --color 0x00FF00 --similarity 0.12
  denoise-video  hqdn3d light denoise: --strength 4
  deinterlace bwdif
  trim        frame-accurate re-encode: --start s --end s
  timecode    burn source timecode top-left (perception proxies)
GPU tools use bin/rife and bin/realesrgan (official releases, SHA256 recorded there).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

BIN = cfg.path("bin")
RIFE = BIN / "rife" / "rife-ncnn-vulkan.exe"
ESRGAN = BIN / "realesrgan" / "realesrgan-ncnn-vulkan.exe"
RIFE_JOBS = "1:1:1"  # see slowmo(): multi-threaded runs glitch on the Arc iGPU
DEEPFILTER = BIN / "deepfilter" / "deep-filter.exe"
ENC = ["-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p"]
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def ff(*args: str, quiet: bool = True) -> None:
    subprocess.run([cfg.ffmpeg(), "-hide_banner", "-y"] + (["-v", "error"] if quiet else []) + list(args), check=True)


def probe(path: Path) -> dict:
    out = subprocess.run([cfg.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                          str(path)], capture_output=True, text=True, encoding="utf-8", check=True).stdout
    d = json.loads(out)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), {})
    num, den = (int(x) for x in v.get("avg_frame_rate", "0/1").split("/")) if v else (0, 1)
    return {"fps": num / den if den and num else 0.0, "w": v.get("width"), "h": v.get("height"),
            "audio": any(s["codec_type"] == "audio" for s in d["streams"]),
            "duration": float(d["format"].get("duration", 0))}


def workdir() -> Path:
    base = cfg.path("cache") / "fx_tmp"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=base))


def gpu_id() -> str:
    return str(cfg.load().get("gpu", {}).get("vulkan_device", 0))


def range_args(start: float | None, end: float | None) -> list[str]:
    a = []
    if start is not None:
        a += ["-ss", f"{start:.4f}"]
    if end is not None:
        a += ["-to", f"{end:.4f}"] if start is None else ["-t", f"{end - start:.4f}"]
    return a


# ---------------------------------------------------------------- slowmo

def _mean_luma(p: Path) -> float:
    import cv2
    import numpy as np
    im = cv2.imdecode(np.fromfile(str(p), np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8)
    return float(im.mean()) if im is not None else 0.0


def rife_frames(fin: Path, fout: Path, n_out: int, keep: int, model: str = "rife-v4.6",
                tries: int = 3) -> tuple[bool, list[str]]:
    """Interpolate the PNG frames in `fin` to `n_out` frames in `fout`, keep the first `keep`.

    rife-ncnn-vulkan places output j at input time j*n/N, so callers ask for n*factor frames (exact
    1/factor steps) and keep (n-1)*factor+1, dropping the frames past the last input.
    On the Arc iGPU RIFE sometimes writes all-black frames or crashes (seen with -j 2:2:2 and the
    default 1:2:2; 1:1:1 was clean in 6/6 runs), so run single-threaded, check every output frame
    against the darkest input frame, and retry. -> (ok, bad frame names)."""
    floor = 0.25 * min(_mean_luma(q) for q in fin.glob("*.png"))
    bad: list[str] = []
    for _ in range(tries):
        for q in fout.glob("*.png"):
            q.unlink()
        r = subprocess.run([str(RIFE), "-i", str(fin), "-o", str(fout), "-m", str(RIFE.parent / model),
                            "-n", str(n_out), "-g", gpu_id(), "-j", RIFE_JOBS], capture_output=True)
        for extra in sorted(fout.glob("*.png"))[keep:]:
            extra.unlink()
        outs = sorted(fout.glob("*.png"))
        bad = [q.name for q in outs if _mean_luma(q) < floor] if r.returncode == 0 else [f"crash {r.returncode}"]
        if r.returncode == 0 and len(outs) == keep and not bad:
            return True, []
    return False, bad


def slowmo(src: Path, out: Path, factor: int = 4, start: float | None = None, end: float | None = None,
           model: str = "rife-v4.6", keep_fps: bool = False, engine: str = "rife") -> dict:
    info = probe(src)
    fps = info["fps"]
    t0 = time.time()
    if engine == "minterpolate":
        target = fps * factor
        chain = f"minterpolate=fps={target}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
        if not keep_fps:
            chain += f",setpts={factor}*PTS"
        ff(*range_args(start, end), "-i", str(src), "-an", "-vf", chain, "-r", str(target if keep_fps else fps),
           *ENC, str(out))
        return {"engine": "minterpolate", "seconds": round(time.time() - t0, 1)}
    wd = workdir()
    try:
        fin, fout = wd / "in", wd / "out"
        fin.mkdir()
        fout.mkdir()
        ff(*range_args(start, end), "-i", str(src), "-an", "-vsync", "0", str(fin / "%08d.png"))
        n = len(list(fin.glob("*.png")))
        target = (n - 1) * factor + 1  # every source frame kept, factor-1 new ones between each pair
        ok, bad = rife_frames(fin, fout, n * factor, target, model)
        if not ok:
            shutil.rmtree(wd, ignore_errors=True)
            res = slowmo(src, out, factor, start, end, model, keep_fps, engine="minterpolate")
            return {**res, "warning": f"RIFE gave bad output 3 times ({bad[:3]}); used minterpolate"}
        out_fps = fps * factor if keep_fps else fps
        ff("-framerate", f"{out_fps}", "-i", str(fout / "%08d.png"), *ENC, str(out))
        return {"engine": f"rife:{model}", "in_frames": n, "out_frames": target,
                "seconds": round(time.time() - t0, 1)}
    finally:
        shutil.rmtree(wd, ignore_errors=True)  # our own temp dir under cache/fx_tmp


# --------------------------------------------------------------- upscale

def upscale(src: Path, out: Path, model: str | None = None, height: int | None = 1080,
            scale: int = 4) -> dict:
    """model None: realesrgan-x4plus for images (best detail), realesr-animevideov3 for video:
    on the Arc x4plus takes ~13 s per 1080p frame vs ~0.4 s (Phase 6 benchmark)."""
    t0 = time.time()
    if model is None:
        model = "realesrgan-x4plus" if src.suffix.lower() in IMAGE_EXT else "realesr-animevideov3"
    if model.startswith("realesr-animevideov3"):
        model = f"realesr-animevideov3-x{scale}" if scale in (2, 3, 4) else "realesr-animevideov3-x4"
    esr = [str(ESRGAN), "-n", model, "-s", str(scale if "animevideov3" in model else 4), "-g", gpu_id(),
           "-m", str(ESRGAN.parent / "models")]
    if src.suffix.lower() in IMAGE_EXT:
        from PIL import Image, ImageOps
        wd = workdir()
        try:
            tmp_in, tmp_out = wd / "in.png", wd / "out.png"
            ImageOps.exif_transpose(Image.open(src)).convert("RGB").save(tmp_in)
            subprocess.run(esr + ["-i", str(tmp_in), "-o", str(tmp_out)], check=True, capture_output=True)
            im = Image.open(tmp_out)
            if height:
                im = im.resize((round(im.width * height / im.height / 2) * 2, height), Image.LANCZOS)
            im.save(out, quality=95) if out.suffix.lower() in (".jpg", ".jpeg") else im.save(out)
            return {"model": model, "size": im.size, "seconds": round(time.time() - t0, 1)}
        finally:
            shutil.rmtree(wd, ignore_errors=True)
    info = probe(src)
    wd = workdir()
    try:
        fin, fout = wd / "in", wd / "out"
        fin.mkdir()
        fout.mkdir()
        ff("-i", str(src), "-vsync", "0", str(fin / "%08d.png"))
        subprocess.run(esr + ["-i", str(fin), "-o", str(fout), "-f", "png"], check=True, capture_output=True)
        vf = f"scale=-2:{height}:flags=lanczos" if height else "null"
        args = ["-framerate", f"{info['fps']}", "-i", str(fout / "%08d.png")]
        if info["audio"]:
            args += ["-i", str(src), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        ff(*args, "-vf", vf, *ENC, str(out))
        return {"model": model, "frames": len(list(fin.glob("*.png"))), "seconds": round(time.time() - t0, 1)}
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ------------------------------------------------------------- stabilize

def stabilize(src: Path, out: Path, smoothing: int = 30, zoom: float = 0, shakiness: int = 6) -> dict:
    t0 = time.time()
    wd = workdir()
    try:
        trf = wd / "transforms.trf"
        # vidstab writes relative paths; run in the work dir to avoid escaping a drive colon
        subprocess.run([cfg.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-i", str(src.resolve()), "-vf",
                        f"vidstabdetect=shakiness={shakiness}:accuracy=15:result=transforms.trf", "-f", "null", "-"],
                       check=True, cwd=wd)
        zoom_opt = f"zoom={zoom}" if zoom else "optzoom=1"
        subprocess.run([cfg.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-i", str(src.resolve()), "-vf",
                        f"vidstabtransform=input=transforms.trf:smoothing={smoothing}:{zoom_opt}:interpol=bicubic,"
                        "unsharp=5:5:0.6:3:3:0.3", *ENC, "-c:a", "copy", str(out.resolve())],
                       check=True, cwd=wd)
        return {"smoothing": smoothing, "seconds": round(time.time() - t0, 1)}
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ----------------------------------------------------------- cut-silence

def cut_silence(src: Path, out: Path, threshold: str = "4%", margin: str = "0.2s") -> dict:
    t0 = time.time()
    exe = cfg.ROOT / ".venv" / "Scripts" / "auto-editor.exe"
    subprocess.run([str(exe), str(src), "--edit", f"audio:threshold={threshold}", "--margin", margin,
                    "-o", str(out), "--no-open"], check=True, capture_output=True)
    return {"in_s": round(probe(src)["duration"], 2), "out_s": round(probe(out)["duration"], 2),
            "seconds": round(time.time() - t0, 1)}


# --------------------------------------------------------- denoise-voice

def denoise_voice(src: Path, out: Path, atten: float = 100, highpass: int = 80) -> dict:
    """High-pass (removes mains hum and rumble, which DeepFilterNet leaves alone) -> DeepFilterNet3."""
    t0 = time.time()
    wd = workdir()
    try:
        wav = wd / "voice.wav"
        hp = ["-af", f"highpass=f={highpass}:poles=2,highpass=f={highpass}:poles=2"] if highpass else []
        ff("-i", str(src), "-vn", "-ac", "1", "-ar", "48000", *hp, "-c:a", "pcm_s16le", str(wav))
        subprocess.run([str(DEEPFILTER), "-a", str(atten), "-D", "-o", str(wd / "df"), str(wav)],
                       check=True, capture_output=True)
        clean = wd / "df" / "voice.wav"
        if src.suffix.lower() in (".wav", ".mp3", ".m4a", ".flac", ".aac", ".ogg"):
            ff("-i", str(clean), str(out))
        else:
            ff("-i", str(src), "-i", str(clean), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
               "-c:a", "aac", "-b:a", "192k", "-shortest", str(out))
        return {"atten_db": atten, "highpass_hz": highpass, "seconds": round(time.time() - t0, 1)}
    finally:
        shutil.rmtree(wd, ignore_errors=True)


# ------------------------------------------------------- simple ffmpeg ops

def atempo_chain(f: float) -> str:
    parts = []
    while f > 2.0:
        parts.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        parts.append("atempo=0.5")
        f /= 0.5
    parts.append(f"atempo={f:.6f}")
    return ",".join(parts)


def speed(src: Path, out: Path, factor: float) -> dict:
    info = probe(src)
    args = ["-i", str(src), "-filter:v", f"setpts=PTS/{factor}"]
    args += ["-filter:a", atempo_chain(factor)] if info["audio"] else ["-an"]
    ff(*args, *ENC, str(out))
    return {"factor": factor}


def lut(src: Path, out: Path, lut_file: Path, mix: float = 1.0) -> dict:
    wd = workdir()
    try:
        shutil.copy(lut_file, wd / "look.cube")
        chain = "lut3d=look.cube" if mix >= 1 else \
            f"split[a][b];[b]lut3d=look.cube[l];[a][l]blend=all_expr='A*(1-{mix})+B*{mix}'"
        subprocess.run([cfg.ffmpeg(), "-hide_banner", "-v", "error", "-y", "-i", str(src.resolve()), "-vf", chain,
                        *ENC, "-c:a", "copy", str(out.resolve())], check=True, cwd=wd)
        return {"lut": str(lut_file), "mix": mix}
    finally:
        shutil.rmtree(wd, ignore_errors=True)


def key(src: Path, out: Path, color: str = "0x00FF00", similarity: float = 0.12, blend: float = 0.05) -> dict:
    vf = f"chromakey={color}:{similarity}:{blend},despill=type=green" if color.lower().endswith("ff00") \
        else f"chromakey={color}:{similarity}:{blend}"
    if out.suffix.lower() == ".webm":
        ff("-i", str(src), "-vf", vf + ",format=yuva420p", "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "24",
           "-auto-alt-ref", "0", str(out))
    else:
        ff("-i", str(src), "-vf", vf + ",format=yuva444p10le", "-c:v", "prores_ks", "-profile:v", "4444", str(out))
    return {"color": color}


def run_simple(kind: str, src: Path, out: Path, a) -> dict:
    if kind == "denoise-video":
        s = a.strength
        ff("-i", str(src), "-vf", f"hqdn3d={s}:{s * 0.75}:{s * 1.5}:{s * 1.1}", *ENC, "-c:a", "copy", str(out))
    elif kind == "deinterlace":
        ff("-i", str(src), "-vf", "bwdif=mode=send_field:parity=auto:deint=all", *ENC, "-c:a", "copy", str(out))
    elif kind == "trim":
        ff(*range_args(a.start, a.end), "-i", str(src), *ENC, "-c:a", "aac", "-b:a", "192k", str(out))
    elif kind == "timecode":
        font = (cfg.path("fonts") / "inter" / "Inter[opsz,wght].ttf").as_posix().replace(":", "\\:")
        ff("-i", str(src), "-vf", f"drawtext=fontfile='{font}':text='%{{pts\\:hms}}':x=12:y=12:fontsize=h/18:"
           "fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=8", *ENC, "-c:a", "copy", str(out))
    return {"op": kind}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("src", type=Path)
        p.add_argument("out", type=Path)
        return p

    p = add("slowmo", "RIFE slow motion")
    p.add_argument("--factor", type=int, default=4)
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)
    p.add_argument("--model", default=cfg.load().get("fx", {}).get("rife_model", "rife-v4.6"))
    p.add_argument("--keep-fps", action="store_true", help="smooth high-fps output at normal speed")
    p.add_argument("--engine", default="rife", choices=["rife", "minterpolate"])
    p = add("upscale", "Real-ESRGAN upscale (image or video)")
    p.add_argument("--model", default=None, help="default: realesrgan-x4plus (images) / realesr-animevideov3 (video)",
                   choices=["realesrgan-x4plus", "realesrgan-x4plus-anime", "realesr-animevideov3"])
    p.add_argument("--height", type=int, default=1080, help="final height (0 = keep the x4 result)")
    p.add_argument("--scale", type=int, default=4)
    p = add("stabilize", "vidstab two-pass")
    p.add_argument("--smoothing", type=int, default=30)
    p.add_argument("--zoom", type=float, default=0)
    p.add_argument("--shakiness", type=int, default=6)
    p = add("cut-silence", "auto-editor silence removal")
    p.add_argument("--threshold", default="4%")
    p.add_argument("--margin", default="0.2s")
    p = add("denoise-voice", "high-pass + DeepFilterNet3 voice denoise")
    p.add_argument("--atten", type=float, default=100, help="max noise reduction dB (lower = gentler)")
    p.add_argument("--highpass", type=int, default=80, help="Hz; 0 disables (keep deep voices' lows)")
    p = add("speed", "constant speed change")
    p.add_argument("--factor", type=float, required=True)
    p = add("lut", "apply a .cube LUT")
    p.add_argument("--lut", type=Path, required=True)
    p.add_argument("--mix", type=float, default=1.0)
    p = add("key", "chroma key to alpha (.mov ProRes 4444 or .webm VP9)")
    p.add_argument("--color", default="0x00FF00")
    p.add_argument("--similarity", type=float, default=0.12)
    p = add("denoise-video", "hqdn3d")
    p.add_argument("--strength", type=float, default=4)
    add("deinterlace", "bwdif")
    p = add("trim", "frame-accurate trim")
    p.add_argument("--start", type=float)
    p.add_argument("--end", type=float)
    add("timecode", "burn-in source timecode")
    a = ap.parse_args()
    if not a.src.exists():
        sys.exit(f"not found: {a.src}")
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.cmd == "slowmo":
        r = slowmo(a.src, a.out, a.factor, a.start, a.end, a.model, a.keep_fps, a.engine)
    elif a.cmd == "upscale":
        r = upscale(a.src, a.out, a.model, a.height or None, a.scale)
    elif a.cmd == "stabilize":
        r = stabilize(a.src, a.out, a.smoothing, a.zoom, a.shakiness)
    elif a.cmd == "cut-silence":
        r = cut_silence(a.src, a.out, a.threshold, a.margin)
    elif a.cmd == "denoise-voice":
        r = denoise_voice(a.src, a.out, a.atten, a.highpass)
    elif a.cmd == "speed":
        r = speed(a.src, a.out, a.factor)
    elif a.cmd == "lut":
        r = lut(a.src, a.out, a.lut, a.mix)
    elif a.cmd == "key":
        r = key(a.src, a.out, a.color, a.similarity)
    else:
        r = run_simple(a.cmd, a.src, a.out, a)
    print(json.dumps({"out": str(a.out), **r}, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

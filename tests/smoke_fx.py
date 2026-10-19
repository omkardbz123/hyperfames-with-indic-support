"""Smoke-test the simple tools/fx.py ops and HyperFrames remove-background: each runs and the
output has the expected stream properties.

Usage:  uv run tests/smoke_fx.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import fx  # noqa: E402
import hf  # noqa: E402

D = ROOT / "tests" / "fixtures" / "fx"
SRC = ROOT / "tests" / "fixtures" / "footage" / "tos_60-180.mp4"


def streams(p: Path) -> dict:
    out = subprocess.run([cfg.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                          str(p)], capture_output=True, text=True, encoding="utf-8").stdout
    d = json.loads(out or "{}")
    v = next((s for s in d.get("streams", []) if s["codec_type"] == "video"), {})
    return {"dur": round(float(d.get("format", {}).get("duration", 0)), 2), "codec": v.get("codec_name"),
            "pix": v.get("pix_fmt"), "w": v.get("width"), "h": v.get("height")}


def main() -> int:
    D.mkdir(parents=True, exist_ok=True)
    clip = D / "clip4s.mp4"
    fx.ff("-ss", "112", "-t", "4", "-i", str(SRC), *fx.ENC, "-c:a", "aac", str(clip))
    green = D / "green.mp4"  # a real frame over pure green, for the keyer
    fx.ff("-f", "lavfi", "-i", "color=c=0x00FF00:s=1280x720:d=2", "-i", str(D / "orig_1080.png"),
          "-filter_complex", "[1:v]scale=640:-2[f];[0:v][f]overlay=320:180", "-t", "2", *fx.ENC, str(green))
    checks = [
        ("speed x2", lambda o: fx.speed(clip, o, 2.0), "speed.mp4", lambda s: abs(s["dur"] - 2.0) < 0.15),
        ("trim 1-2.5 s", lambda o: fx.run_simple("trim", clip, o, type("A", (), {"start": 1.0, "end": 2.5})),
         "trim.mp4", lambda s: abs(s["dur"] - 1.5) < 0.1),
        ("denoise-video", lambda o: fx.run_simple("denoise-video", clip, o, type("A", (), {"strength": 4})),
         "dnv.mp4", lambda s: s["codec"] == "h264"),
        ("deinterlace", lambda o: fx.run_simple("deinterlace", clip, o, None), "deint.mp4",
         lambda s: s["codec"] == "h264"),
        ("timecode burn-in", lambda o: fx.run_simple("timecode", clip, o, None), "tc.mp4",
         lambda s: s["codec"] == "h264"),
        ("chroma key -> ProRes 4444", lambda o: fx.key(green, o), "keyed.mov",
         lambda s: s["codec"] == "prores" and "a" in (s["pix"] or "")),
        ("chroma key -> WebM alpha", lambda o: fx.key(green, o), "keyed.webm",
         lambda s: s["codec"] == "vp9"),
    ]
    ok = True
    for name, fn, out, test in checks:
        t0 = time.time()
        try:
            fn(D / out)
            s = streams(D / out)
            good = test(s)
        except Exception as e:  # noqa: BLE001
            s, good = {"error": str(e)[:120]}, False
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {name:<28} {s}  {time.time() - t0:.1f}s")
    # HyperFrames background removal (local u2net_human_seg)
    t0 = time.time()
    img = ROOT / "tests" / "fixtures" / "photos" / "p05.jpg"
    out = D / "cutout.png"
    p = hf.run(["remove-background", str(img), "-o", str(out)])
    good = p.returncode == 0 and out.exists()
    if good:
        from PIL import Image
        a = Image.open(out)
        good = a.mode in ("RGBA", "LA")
        alpha = a.getchannel("A") if good else None
        frac = sum(1 for v in alpha.getdata() if v > 128) / (a.width * a.height) if alpha else 0
        print(f"{'PASS' if good else 'FAIL'}  remove-background (photo)    {a.size} {a.mode}, "
              f"foreground {frac:.0%}  {time.time() - t0:.1f}s")
    else:
        print(f"FAIL  remove-background (photo)    exit {p.returncode}")
    ok &= good
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

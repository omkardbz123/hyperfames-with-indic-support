"""Export a reviewed project: per-platform files + poster + credits + caption + report.

Usage:  uv run tools/export.py projects/<slug> [--presets reels,whatsapp,feed45,square,youtube,master]
                               [--force-unconfirmed] [--allow-unknown] [--skip-review] [--gemini]

Steps:
 1. refuse while brand facts are unconfirmed (`to_confirm`) or an asset has no licence, unless forced
 2. master render of the project at delivery quality (renders/master.mp4)
 3. per preset (config/export_presets.toml): same aspect as the project -> transcode the master;
    another aspect -> a layout variant (tools/build.py --format, footage re-framed, text re-laid out
    for that format's safe zones) rendered and transcoded. Audio is always the project's own
    mastered mix.wav (exact loudness), encoded per preset.
 4. validate every file: size, fps, codec, duration, loudness (-14 ±1 LUFS, TP <= -1.5), bitrate cap
 5. exports/<slug>/: <slug>_<preset>.mp4 (.mov for master), poster.jpg, CREDITS.txt,
    caption.txt (post text + hashtags + credit line), report.md (review + validation + credits)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import edl as E  # noqa: E402

PRESET_FORMAT = {"reels": "reels", "shorts": "reels", "whatsapp": "reels", "feed45": "feed45", "square": "square",
                 "youtube": "youtube"}


def presets() -> dict:
    import tomllib
    raw = tomllib.loads((cfg.ROOT / "config" / "export_presets.toml").read_text(encoding="utf-8"))
    out = {}
    for name, p in raw.items():
        base = dict(raw.get(p.get("inherit"), {})) if p.get("inherit") else {}
        base.update({k: v for k, v in p.items() if k != "inherit"})
        out[name] = base
    return out


def aspect(w: int, h: int) -> float:
    return round(w / h, 3)


def render_master(project: Path) -> Path:
    import hf
    out = project / "renders" / "master.mp4"
    bj = json.loads((project / "build.json").read_text(encoding="utf-8"))
    built = time.mktime(time.strptime(bj["built_at"], "%Y-%m-%dT%H:%M:%S"))
    if out.exists() and out.stat().st_mtime > built:
        return out
    print(f"[export] master render of {project.name} (delivery quality)", flush=True)
    r = hf.run(["render", "-o", "renders/master.mp4", "--quality", "delivery", "--quiet"], cwd=project)
    if r.returncode:
        raise SystemExit(f"master render failed in {project}")
    mix = project / "assets" / "audio" / "mix.wav"
    if mix.exists():
        import build
        build.remux_audio(out, mix, "320k")
    return out


def encode(master: Path, mix: Path | None, p: dict, out: Path, duration: float) -> None:
    w, h = p.get("width"), p.get("height")
    vf = []
    if w and h:
        vf.append(f"scale={w}:{h}:flags=lanczos")
    if p.get("fps"):
        vf.append(f"fps={p['fps']}")
    vf.append(f"format={p.get('pix_fmt', 'yuv420p')}")
    args = [cfg.ffmpeg(), "-v", "error", "-y", "-i", str(master)]
    if mix:
        args += ["-i", str(mix), "-map", "0:v:0", "-map", "1:a:0"]
    else:
        args += ["-map", "0:v:0", "-map", "0:a?"]
    args += ["-t", f"{duration:.3f}", "-vf", ",".join(vf), "-c:v", p["vcodec"]]
    if p["vcodec"] == "libx264":
        args += ["-profile:v", p.get("profile", "high"), "-preset", "slow", "-crf", str(p.get("crf", 19))]
        if p.get("maxrate"):
            args += ["-maxrate", p["maxrate"], "-bufsize", p.get("bufsize", p["maxrate"])]
        args += ["-g", str(int(p.get("fps", 30)) * 2)]
    elif p["vcodec"] == "prores_ks":
        args += ["-profile:v", str(p.get("profile", "3")), "-vendor", "apl0"]
    args += ["-c:a", p.get("acodec", "aac")]
    if p.get("abitrate"):
        args += ["-b:a", p["abitrate"]]
    args += ["-ar", str(p.get("ar", 48000))]
    if p.get("faststart"):
        args += ["-movflags", "+faststart"]
    args.append(str(out))
    subprocess.run(args, check=True)


def validate(out: Path, p: dict, duration: float) -> dict:
    import audiolib as al
    d = json.loads(subprocess.run([cfg.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                                   str(out)], capture_output=True, text=True, encoding="utf-8").stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    n, m = (int(x) for x in v["r_frame_rate"].split("/"))
    dur = float(d["format"]["duration"])
    mbps = float(d["format"].get("bit_rate", 0)) / 1e6
    probs = []
    if p.get("width") and (v["width"], v["height"]) != (p["width"], p["height"]):
        probs.append(f"size {v['width']}x{v['height']}")
    if p.get("fps") and abs(n / m - p["fps"]) > 0.01:
        probs.append(f"fps {n / m:g}")
    if abs(dur - duration) > 0.1:
        probs.append(f"duration {dur:.2f}s (want {duration:.2f})")
    if p.get("maxrate"):
        cap = float(p["maxrate"].rstrip("M"))
        if mbps > cap * 1.05:
            probs.append(f"bitrate {mbps:.1f} Mb/s > {cap:g}")
    L = al.loudness(out) if a else {"I": None, "TP": None}
    if a and (L["I"] is None or abs(L["I"] + 14) > 1 or L["TP"] > -1.5):
        probs.append(f"loudness {L['I']} LUFS / TP {L['TP']}")
    return {"file": out.name, "size": f"{v['width']}x{v['height']}", "fps": round(n / m, 3), "vcodec": v["codec_name"],
            "duration": round(dur, 3), "mbps": round(mbps, 2), "MB": round(out.stat().st_size / 1e6, 1),
            "lufs": L["I"], "tp": L["TP"], "ok": not probs, "problems": probs}


def poster(master: Path, bj: dict, out: Path) -> Path:
    t = bj.get("poster_at")
    if t is None:
        titles = [x for x in bj.get("text", []) if x.get("style") in ("title", "big")]
        t = (titles[0]["at"] + 0.9) if titles else bj["duration"] / 3
    subprocess.run([cfg.ffmpeg(), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(master), "-frames:v", "1",
                    "-q:v", "2", str(out)], check=True)
    return out


def export(project: Path, names: list[str], force_unconfirmed: bool = False, allow_unknown: bool = False,
           skip_review: bool = False, gemini: bool = False) -> dict:
    import credits
    project = Path(project).resolve()
    bj = json.loads((project / "build.json").read_text(encoding="utf-8"))
    if bj.get("unconfirmed_facts") and not force_unconfirmed:
        raise SystemExit("export refused: brand facts not confirmed yet:\n  - " + "\n  - ".join(bj["unconfirmed_facts"])
                         + "\nconfirm them with the user (library/brands/<brand>/brand.json) or pass --force-unconfirmed for a draft")
    files, models, fonts, title = credits.from_project(project)
    ctext, cline, unknown = credits.build(files, models, fonts, title, allow_unknown=True)
    if unknown and not allow_unknown:
        raise SystemExit("export refused: no licence for:\n  - " + "\n  - ".join(unknown) +
                         "\nask the user (tools/ingest.py --own) or pass --allow-unknown for a private draft")
    P = presets()
    bad = [n for n in names if n not in P]
    if bad:
        raise SystemExit(f"unknown preset(s) {bad}; have {sorted(P)}")
    out_dir = cfg.ROOT / "exports" / bj["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    master = render_master(project)
    review_res = None
    if not skip_review:
        import review
        review_res = review.review(project, render=master, gemini=gemini)
    mix = project / "assets" / "audio" / "mix.wav"
    W, H = bj["format"]["w"], bj["format"]["h"]
    rows = []
    for name in names:
        p = P[name]
        src_master, src_mix, D = master, (mix if mix.exists() else None), bj["duration"]
        if p.get("width") and aspect(p["width"], p["height"]) != aspect(W, H):
            fmt = PRESET_FORMAT[name]
            import build
            vdir = project / "variants" / fmt
            print(f"[export] layout variant {fmt} for {name}", flush=True)
            build.build(project, fmt_override=fmt)
            src_master = render_master(vdir)
            vmix = vdir / "assets" / "audio" / "mix.wav"
            src_mix = vmix if vmix.exists() else None
        ext = ".mov" if p.get("container") == "mov" else ".mp4"
        out = out_dir / f"{bj['slug']}_{name}{ext}"
        print(f"[export] {name} -> {out.name}", flush=True)
        encode(src_master, src_mix, p, out, D)
        rows.append({"preset": name, **validate(out, p, D)})
    poster(master, bj, out_dir / "poster.jpg")
    (out_dir / "CREDITS.txt").write_text(ctext, encoding="utf-8")
    post = (bj.get("caption_post") or "").strip()
    tags = " ".join(bj.get("hashtags") or [])
    (out_dir / "caption.txt").write_text("\n\n".join(x for x in (post, tags, cline) if x) + "\n", encoding="utf-8")
    ok = all(r["ok"] for r in rows) and (review_res is None or review_res["ok"])
    rep = [f"# Export report: {bj['title']}", "", f"{time.strftime('%Y-%m-%d %H:%M')} · {len(rows)} file(s) · "
           f"**{'OK' if ok else 'PROBLEMS'}**", "",
           "| Preset | File | Size | fps | Duration | Mb/s | MB | LUFS | TP | OK |", "|---|---|---|---|---|---|---|---|---|---|"]
    rep += [f"| {r['preset']} | {r['file']} | {r['size']} | {r['fps']:g} | {r['duration']} | {r['mbps']} | {r['MB']} | {r['lufs']} | "
            f"{r['tp']} | {'yes' if r['ok'] else 'NO: ' + '; '.join(r['problems'])} |" for r in rows]
    if review_res:
        rep += ["", "## Review", *[f"- **{c['name']}** {c['status']}: {c['detail']}" for c in review_res["checks"]],
                "", f"Contact sheet: `{Path(review_res['sheet']).relative_to(cfg.ROOT).as_posix()}`"]
    if bj.get("unconfirmed_facts"):
        rep += ["", "## ⚠ Draft: brand facts NOT confirmed", *[f"- {f}" for f in bj["unconfirmed_facts"]]]
    if unknown:
        rep += ["", "## ⚠ Private draft: assets without a licence (do not post)", *[f"- {u}" for u in unknown]]
    rep += ["", "## Caption credit line", cline, "", "## Credits", "```", ctext.strip(), "```"]
    (out_dir / "report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    for r in rows:
        print(f"  {r['preset']:<9} {r['file']:<34} {r['size']:<10} {r['MB']:>6} MB  {r['lufs']} LUFS  "
              + ("ok" if r["ok"] else "PROBLEMS: " + "; ".join(r["problems"])))
    print(f"[export] {'OK' if ok else 'PROBLEMS'} -> {out_dir}")
    return {"ok": ok, "rows": rows, "dir": str(out_dir)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--presets", default="reels,whatsapp")
    ap.add_argument("--force-unconfirmed", action="store_true")
    ap.add_argument("--allow-unknown", action="store_true")
    ap.add_argument("--skip-review", action="store_true")
    ap.add_argument("--gemini", action="store_true")
    a = ap.parse_args()
    res = export(a.project, [x.strip() for x in a.presets.split(",") if x.strip()], a.force_unconfirmed,
                 a.allow_unknown, a.skip_review, a.gemini)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

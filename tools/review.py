"""Review a render before export: automated QA (BUILD_PLAN §11) + contact sheet + optional Gemini.

Usage:  uv run tools/review.py projects/<slug> [--render renders/draft.mp4] [--gemini] [--no-hf-check]

Checks (each pass / warn / fail, with a fix suggestion):
  technical   resolution, fps, codec, pixel format, duration (±1 frame), audio stream present
  loudness    integrated -14 LUFS ±1, true peak <= -1.5 dBTP (ebur128 on the render)
  black       black stretches (blackdetect) outside intended dark parts (end card, dark cards, dips)
  freeze      frozen picture (freezedetect, >= 1 s) inside video clips
  cut_sync    every snapped hard cut in the render within ±1 frame of its anchor (PySceneDetect
              on the render vs build.json anchors)
  captions    pages never overlap; word times = aligner times (±80 ms); caption band in the safe zone
  safe_zone   every title / end-card line inside the platform safe zone, no overflow (measured in
              Chrome: tools/js/measure_text.mjs)
  glyphs      every character of every text exists in its font (no tofu boxes)
  facts       brand facts still to confirm (export is blocked until confirmed)
  licences    every asset has a licence (tools/credits.py)
  hyperframes `hyperframes check` (lint, runtime errors, layout overflow, WCAG contrast)
  gemini      (--gemini) perceive.py review_render on the render, with audio: advisory only
Writes projects/<slug>/review/{review.json, review.md, sheet.jpg}. Look at sheet.jpg yourself.
Exit code 1 when any check fails.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

IGNORE_CHARS = {" ", "‌", "‍", "\n", "\t", " "}


class Report:
    def __init__(self):
        self.checks: list[dict] = []

    def add(self, name: str, status: str, detail: str, fix: str = "") -> None:
        self.checks.append({"name": name, "status": status, "detail": detail, "fix": fix})
        mark = {"pass": "ok  ", "warn": "WARN", "fail": "FAIL", "info": "info"}[status]
        print(f"[{mark}] {name}: {detail}" + (f"\n        fix: {fix}" if fix and status != "pass" else ""), flush=True)


def ff_stderr(args: list[str]) -> str:
    return subprocess.run([cfg.ffmpeg(), "-hide_banner", "-nostats", *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stderr


def overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


# ------------------------------------------------------------------ checks

def chk_technical(r: Report, video: Path, bj: dict) -> dict:
    out = subprocess.run([cfg.ffprobe(), "-v", "error", "-print_format", "json", "-show_streams", "-show_format",
                          str(video)], capture_output=True, text=True, encoding="utf-8").stdout
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = [s for s in d["streams"] if s["codec_type"] == "audio"]
    n, m = (int(x) for x in v["r_frame_rate"].split("/"))
    fps = n / m
    f = bj["format"]
    probs = []
    if (v["width"], v["height"]) != (f["w"], f["h"]):
        probs.append(f"size {v['width']}x{v['height']} != {f['w']}x{f['h']}")
    if abs(fps - f["fps"]) > 0.01:
        probs.append(f"fps {fps:g} != {f['fps']:g}")
    if v["codec_name"] != "h264" or v.get("pix_fmt") != "yuv420p":
        probs.append(f"{v['codec_name']}/{v.get('pix_fmt')} (want h264/yuv420p)")
    dur = float(d["format"]["duration"])
    if abs(dur - bj["duration"]) > 1 / f["fps"] + 0.05:
        probs.append(f"duration {dur:.3f}s != {bj['duration']}s")
    if bj.get("loudness") and not a:
        probs.append("no audio stream")
    br = float(d["format"].get("bit_rate", 0)) / 1e6
    r.add("technical", "fail" if probs else "pass",
          "; ".join(probs) or f"{v['width']}x{v['height']} {fps:g} fps h264 yuv420p, {dur:.2f}s, {br:.1f} Mb/s, audio {'yes' if a else 'no'}",
          "rebuild/re-render; check the EDL format and duration")
    return {"duration": dur, "fps": fps}


def chk_loudness(r: Report, video: Path, bj: dict) -> None:
    if not bj.get("loudness"):
        r.add("loudness", "info", "no soundtrack in this build")
        return
    import audiolib as al
    L = al.loudness(video)
    probs = []
    if L["I"] is None or abs(L["I"] + 14) > 1.0:
        probs.append(f"integrated {L['I']} LUFS (want -14 ±1)")
    if L["TP"] is None or L["TP"] > -1.5:
        probs.append(f"true peak {L['TP']} dBTP (want <= -1.5; > 0 means clipping)")
    r.add("loudness", "fail" if probs else "pass", "; ".join(probs) or f"{L['I']} LUFS, TP {L['TP']} dBTP, LRA {L['LRA']}",
          "re-run tools/build.py (the mix is mastered to -14 LUFS / -2 dBTP); don't change mix.wav by hand")


def expected_dark(bj: dict) -> list[tuple[float, float]]:
    spans = []
    if bj.get("endcard"):
        spans.append((float(bj["endcard"]["at"]), float(bj["endcard"].get("until") or bj["duration"])))
    for c in bj["clips"]:
        if c["kind"] == "color":
            spans.append((c["tl_start"], c["tl_end"]))
        tr = c.get("transition") or {}
        if tr.get("type") == "dip":
            spans.append((c["at"] - tr["dur"], c["at"] + tr["dur"]))
    return spans


def chk_black(r: Report, video: Path, bj: dict) -> None:
    err = ff_stderr(["-i", str(video), "-vf", "blackdetect=d=0.08:pix_th=0.06", "-an", "-f", "null", "-"])
    segs = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]
    exp = expected_dark(bj)
    bad = [(a, b) for a, b in segs if sum(overlap(a, b, x, y) for x, y in exp) < 0.8 * (b - a)]
    r.add("black", "fail" if bad else "pass",
          (f"unexpected black: " + ", ".join(f"{a:.2f}-{b:.2f}s" for a, b in bad)) if bad else
          f"{len(segs)} dark stretch(es), all intended" if segs else "no black frames",
          "a clip is missing or ends early: check data-start/duration in index.html and the prepped clip lengths")


def chk_freeze(r: Report, video: Path, bj: dict) -> None:
    err = ff_stderr(["-i", str(video), "-vf", "freezedetect=n=-55dB:d=1.0", "-an", "-f", "null", "-"])
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", err)] + [bj["duration"]] * 3
    segs = list(zip(starts, ends))
    vids = [(c["tl_start"], c["tl_end"], c["id"]) for c in bj["clips"] if c["kind"] == "video"]
    bad = [(a, b, cid) for a, b in segs for x, y, cid in vids if overlap(a, b, x, y) >= 1.0]
    if bad and bj.get("recipe") == "tutorial":  # screen recordings sit still while the voice explains
        r.add("freeze", "info", f"{len(bad)} still stretch(es) in screen footage (normal for a tutorial)")
        return
    r.add("freeze", "fail" if bad else "pass",
          ("frozen video: " + ", ".join(f"{a:.2f}-{b:.2f}s in {cid}" for a, b, cid in bad)) if bad else
          f"{len(segs)} still stretch(es), none inside video clips" if segs else "no frozen picture",
          "the source range ran past the end of the footage, or a prep step failed: check src_in/src_out")


def luma_frames(video: Path, fps: float, w: int = 90, h: int = 160):
    """Every frame as a small grey image (frame i is at i/fps)."""
    import numpy as np
    raw = subprocess.run([cfg.ffmpeg(), "-v", "error", "-i", str(video), "-vf", f"scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32)


def find_cut(frames, fps: float, t: float, win: float = 0.5) -> tuple[float | None, float]:
    """The frame with the biggest picture change near t -> (cut time, strength vs the local median)."""
    import numpy as np
    i0, i1 = max(1, int((t - win) * fps)), min(len(frames) - 1, int((t + win) * fps) + 1)
    if i1 <= i0:
        return None, 0.0
    d = np.array([np.abs(frames[i] - frames[i - 1]).mean() for i in range(i0, i1 + 1)])
    med = np.median(d) + 1.0
    # first: is there a clear change within +-1 frame of the anchor? (a jump cut inside one shot is
    # only a framing change and can be smaller than the speaker's own movement elsewhere)
    ke = int(round(t * fps)) - i0
    near = [k for k in range(ke - 1, ke + 2) if 0 <= k < len(d)]
    if near:
        k = max(near, key=lambda j: d[j])
        if d[k] / med >= 2.0:
            return (i0 + k) / fps, float(d[k] / med)
    k = int(d.argmax())
    strength = float(d[k] / med)
    return ((i0 + k) / fps, strength) if strength >= 2.0 else (None, strength)


def chk_cut_sync(r: Report, video: Path, bj: dict) -> list[dict]:
    fps = bj["format"]["fps"]
    hard = {c["id"]: c for c in bj["clips"] if (c.get("transition") or {}).get("type", "cut") in ("cut", "flash")}
    anchored = [k for k in bj["cuts"] if k["anchor"] is not None and k["clip"] in hard and k["t"] > 0]
    if not anchored:
        r.add("cut_sync", "info", "no snapped hard cuts to check")
        return []
    frames = luma_frames(video, fps)
    rows, bad, missing = [], [], []
    for k in anchored:
        near, strength = find_cut(frames, fps, k["anchor"])
        if near is None:
            missing.append(k["clip"])
            rows.append({**k, "detected": None, "error_frames": None, "strength": round(strength, 1)})
            continue
        err = (near - k["anchor"]) * fps
        rows.append({**k, "detected": round(near, 4), "error_frames": round(err, 2), "strength": round(strength, 1)})
        # the cut lands on a frame boundary; the anchor can sit anywhere inside a frame: allow 1 frame + rounding
        if abs(err) > 1.5:
            bad.append(f"{k['clip']} at {near:.3f}s vs {k['kind']} {k['anchor']:.3f}s ({err:+.1f} frames)")
    worst = max((abs(x["error_frames"]) for x in rows if x["error_frames"] is not None), default=0)
    status = "fail" if bad else "warn" if missing else "pass"
    r.add("cut_sync", status,
          "; ".join(bad) if bad else (f"{len(rows) - len(missing)}/{len(rows)} snapped cuts within ±1 frame (worst {worst:.1f} f)"
                                      + (f"; no clear picture change near: {missing}" if missing else "")),
          "the render's cut moved away from its beat: rebuild from edl.json (don't hand-edit index.html)")
    return rows


def parse_captions(project: Path) -> tuple[list[dict], list[dict], str] | None:
    p = project / "compositions" / "captions.html"
    if not p.exists():
        return None
    s = p.read_text(encoding="utf-8")
    W = json.loads(re.search(r"var W = (\[.*?\]);\n", s, re.S).group(1))
    C = json.loads(re.search(r"var C = (\[.*?\]);\n", s, re.S).group(1))
    return W, C, s


def chk_captions(r: Report, project: Path, bj: dict) -> None:
    cap = bj.get("captions")
    parsed = parse_captions(project)
    if not cap or not parsed:
        r.add("captions", "info", "no captions in this build")
        return
    W, C, css = parsed
    probs = []
    for a, b in zip(C, C[1:]):
        if a["e"] > b["s"] + 0.001:
            probs.append(f"pages overlap {a['e']:.2f}>{b['s']:.2f}s")
    words = cap["words"]
    if len(words) != len(W):
        probs.append(f"{len(W)} caption words vs {len(words)} aligned words")
    else:
        off = [abs(w["s"] - x["start"]) for w, x in zip(W, words)]
        late = [i for i, o in enumerate(off) if o > 0.08]
        if late:
            probs.append(f"{len(late)} word(s) more than 80 ms off the aligner (e.g. '{W[late[0]]['t']}')")
    short = [c for c in C if c["e"] - c["s"] < 0.25]
    m = re.search(r"-stage \{ position: absolute; left: (\d+)px; width: (\d+)px; bottom: (\d+)px; height: (\d+)px", css)
    z = bj.get("safe_zone", {})
    if m and z:
        left, width, bottom, height = (int(x) for x in m.groups())
        Wd, Hd = bj["format"]["w"], bj["format"]["h"]
        if left < z["left"] or Wd - left - width < z["right"] or bottom < z["bottom"] or Hd - bottom - height < z["top"]:
            probs.append("caption band outside the safe zone")
    status = "fail" if probs else "warn" if short else "pass"
    r.add("captions", status, "; ".join(probs) or (f"{len(C)} pages, no overlaps, words match the aligner"
                                                   + (f"; {len(short)} page(s) shorter than 0.25 s" if short else "")),
          "rebuild captions from the transcript (tools/build.py / caption_comp.py); pages come from tools/captions.py")


def chk_safe_zone(r: Report, project: Path, bj: dict) -> None:
    jobs = [{"id": f"tx{k}", "t": t["at"]} for k, t in enumerate(bj.get("text", []))]
    if bj.get("endcard"):
        jobs.append({"id": "endcard", "t": bj["endcard"]["at"]})
    if not jobs:
        r.add("safe_zone", "info", "no titles")
        return
    W, H = bj["format"]["w"], bj["format"]["h"]
    z = bj["safe_zone"]
    res = subprocess.run(["node", str(cfg.ROOT / "tools" / "js" / "measure_text.mjs"), str(project), str(cfg.path("chrome")),
                          str(W), str(H), json.dumps(jobs)], capture_output=True, text=True, encoding="utf-8", cwd=cfg.ROOT)
    if res.returncode:
        r.add("safe_zone", "warn", f"could not measure: {res.stderr.strip()[-200:]}")
        return
    rows = json.loads(res.stdout.strip().splitlines()[-1])
    tol = 4
    bad = []
    for row in rows:
        if row["box"] is None:
            continue
        x0, y0, x1, y1 = row["box"]
        out = []
        if x0 < z["left"] - tol: out.append(f"left {x0}px")  # noqa: E701
        if x1 > W - z["right"] + tol: out.append(f"right {x1}px")  # noqa: E701
        if y0 < z["top"] - tol: out.append(f"top {y0}px")  # noqa: E701
        if y1 > H - z["bottom"] + tol: out.append(f"bottom {y1}px")  # noqa: E701
        if row["overflow"]: out.append("text overflows its box")  # noqa: E701
        if out:
            bad.append(f"{row['id']}: " + ", ".join(out))
    r.add("safe_zone", "fail" if bad else "pass", "; ".join(bad) or f"{len(rows)} text block(s) inside the safe zone "
          f"(top {z['top']}, bottom {z['bottom']}, left {z['left']}, right {z['right']} px)",
          "shorten the text, use a smaller size, or move it (pos) in edl.json")


def chk_glyphs(r: Report, bj: dict) -> None:
    from fontTools.ttLib import TTFont
    cmaps: dict[str, set] = {}
    bad = []
    for g in bj.get("glyphs", []):
        if g["file"] not in cmaps:
            cmaps[g["file"]] = set(TTFont(g["file"], lazy=True).getBestCmap())
        miss = sorted({ch for ch in g["text"] if ch not in IGNORE_CHARS and ord(ch) not in cmaps[g["file"]]})
        if miss:
            bad.append(f"{g['font']} lacks {''.join(miss)!r} in '{g['text'][:30]}'")
    r.add("glyphs", "fail" if bad else "pass", "; ".join(bad[:5]) or
          f"{len(bj.get('glyphs', []))} text(s) checked: every character exists in its font",
          "use a font that covers the script (Devanagari: Mukta, Hind, Noto Sans Devanagari, Baloo 2)")


def chk_facts(r: Report, bj: dict) -> None:
    u = bj.get("unconfirmed_facts") or []
    r.add("facts", "warn" if u else "pass", ("to confirm with the user: " + "; ".join(u)) if u else
          "no unconfirmed brand facts", "confirm with the user, update library/brands/<brand>/brand.json (to_confirm)")


def chk_licences(r: Report, project: Path) -> None:
    import credits
    files, models, fonts, title = credits.from_project(project)
    _, _, unknown = credits.build(files, models, fonts, title, allow_unknown=True)
    r.add("licences", "fail" if unknown else "pass",
          ("unknown licence: " + ", ".join(Path(u).name for u in unknown)) if unknown else f"{len(files)} asset(s), all licensed",
          "ask the user (own footage -> tools/ingest.py --own), or add <file>.license.json")


def chk_hf(r: Report, project: Path, bj: dict) -> None:
    import hf
    times = sorted({round(min(bj["duration"] - 0.05, t + 0.4), 2) for t in
                    [k["t"] for k in bj["cuts"]] + [t["at"] for t in bj.get("text", [])]})[:24]
    p = subprocess.run(hf.hf_cmd() + ["check", "--json", "--at", ",".join(f"{t:g}" for t in times)], env=hf.hf_env(),
                       cwd=project, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = p.stdout
    try:
        d = json.loads(out[out.index("{"): out.rindex("}") + 1])
    except ValueError:
        r.add("hyperframes", "warn", f"check gave no JSON (rc {p.returncode})")
        return
    errs, warns = [], []
    for part in ("lint", "runtime", "layout", "contrast"):
        sec = d.get(part) or {}
        for f in sec.get("findings", []):
            if f.get("severity") == "info":  # e.g. a zoom punch briefly overflowing its scene: intended
                continue
            msg = f"{part}: {f.get('code') or f.get('rule') or ''} {f.get('message', '')[:120]}".strip()
            (errs if f.get("severity") == "error" else warns).append(msg)
    r.add("hyperframes", "fail" if errs else "warn" if warns else "pass",
          "; ".join((errs + warns)[:4]) or "lint, runtime, layout and contrast clean",
          "see `uv run tools/hf.py check` in the project for details")


def chk_gemini(r: Report, video: Path) -> dict | None:
    import perceive
    try:
        res = perceive.perceive(video, "review_render")
    except SystemExit as e:
        r.add("gemini", "warn", f"agy review unavailable: {e}", "uv run tools/perceive.py <render> --preset review_render --relay")
        return None
    ans = res.get("result") or {}
    issues = ans.get("issues", [])
    high = [i for i in issues if i.get("severity") == "high"]
    r.add("gemini", "warn" if high else "pass",
          f"score {ans.get('score')}/10; {len(issues)} note(s)" + (": " + "; ".join(f"[{i.get('t', '?')}] {i['detail']}" for i in high[:3]) if high else ""),
          "advisory (verify against the render; Gemini timing is approximate)")
    return ans


# ------------------------------------------------------------------ sheet

def contact_sheet(video: Path, bj: dict, out: Path) -> Path:
    from PIL import Image, ImageDraw
    import numpy as np
    fps = bj["format"]["fps"]
    marks = [(k["t"] + 2 / fps, f"cut {k['clip']}") for k in bj["cuts"]]
    marks += [(t["at"] + 0.7, "text") for t in bj.get("text", [])]
    if bj.get("endcard"):
        marks.append((bj["endcard"]["at"] + 1.4, "end card"))
    for q in (bj.get("captions") or {}).get("cues", [])[:: max(1, len((bj.get("captions") or {}).get("cues", [])) // 6 or 1)]:
        marks.append(((q["start"] + q["end"]) / 2, "caption"))
    marks.sort()
    keep = []
    for t, lab in marks:
        if t < bj["duration"] and (not keep or t - keep[-1][0] > 0.3):
            keep.append((t, lab))
    keep = keep[:36]
    W, H = bj["format"]["w"], bj["format"]["h"]
    tw = 240
    th = round(tw * H / W)
    cols = 6
    rows = (len(keep) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 22)), (20, 20, 22))
    dr = ImageDraw.Draw(sheet)
    for i, (t, lab) in enumerate(keep):
        raw = subprocess.run([cfg.ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
                              "-vf", f"scale={tw}:{th}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        if len(raw) == tw * th * 3:
            sheet.paste(Image.fromarray(np.frombuffer(raw, np.uint8).reshape(th, tw, 3)), ((i % cols) * tw, (i // cols) * (th + 22)))
        m, s = divmod(t, 60)
        dr.text(((i % cols) * tw + 4, (i // cols) * (th + 22) + th + 4), f"{int(m):02d}:{s:05.2f} {lab}", fill=(230, 230, 230))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)
    return out


def review(project: Path, render: Path | None = None, gemini: bool = False, hf_check: bool = True) -> dict:
    project = Path(project).resolve()
    bj = json.loads((project / "build.json").read_text(encoding="utf-8"))
    name = Path(bj.get("render", {}).get("file") or "draft.mp4").name  # always this project's renders/ folder
    video = Path(render) if render else project / "renders" / name
    if not video.is_absolute():
        video = project / video
    if not video.exists():
        raise SystemExit(f"no render at {video}: run tools/build.py {project} --render")
    print(f"reviewing {video}")
    r = Report()
    chk_technical(r, video, bj)
    chk_loudness(r, video, bj)
    chk_black(r, video, bj)
    chk_freeze(r, video, bj)
    cuts = chk_cut_sync(r, video, bj)
    chk_captions(r, project, bj)
    chk_safe_zone(r, project, bj)
    chk_glyphs(r, bj)
    chk_facts(r, bj)
    chk_licences(r, project)
    if hf_check:
        chk_hf(r, project, bj)
    g = chk_gemini(r, video) if gemini else None
    for w in bj.get("warnings", []):
        if "to confirm" not in w:
            r.add("build", "warn", w)
    sheet = contact_sheet(video, bj, project / "review" / "sheet.jpg")
    fails = [c for c in r.checks if c["status"] == "fail"]
    warns = [c for c in r.checks if c["status"] == "warn"]
    res = {"render": str(video), "reviewed_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ok": not fails,
           "checks": r.checks, "cuts": cuts, "gemini": g, "sheet": str(sheet),
           "fixes": [f"{c['name']}: {c['fix']}" for c in fails + warns if c["fix"]]}
    (project / "review" / "review.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    md = [f"# Review: {bj['title']}", "", f"Render: `{video.name}` · {res['reviewed_at']} · "
          f"**{'PASS' if not fails else 'FAIL'}** ({len(fails)} fail, {len(warns)} warn)", "",
          "| Check | Status | Detail |", "|---|---|---|"]
    md += [f"| {c['name']} | {c['status']} | {c['detail'].replace('|', '/')} |" for c in r.checks]
    if res["fixes"]:
        md += ["", "## Fix list", *[f"- {f}" for f in res["fixes"]]]
    if g:
        md += ["", "## Gemini review (advisory)", g.get("overall", ""), *[f"- [{i.get('severity')}] {i.get('t', '')} {i['detail']}"
                                                                         + (f" → {i['fix']}" if i.get("fix") else "") for i in g.get("issues", [])]]
    md += ["", "Contact sheet: `review/sheet.jpg` (look at it)."]
    (project / "review" / "review.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\n{'PASS' if not fails else 'FAIL'}: {len(fails)} fail, {len(warns)} warn -> {project / 'review' / 'review.md'}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--render", type=Path)
    ap.add_argument("--gemini", action="store_true")
    ap.add_argument("--no-hf-check", action="store_true")
    a = ap.parse_args()
    res = review(a.project, a.render, a.gemini, not a.no_hf_check)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

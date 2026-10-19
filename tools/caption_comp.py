"""Caption layer for a HyperFrames project: timed words -> a sub-composition HTML.

Usage:  uv run tools/caption_comp.py <transcript.json|vo.json> --project projects/<slug>
                                     [--style kinetic|pill|pop] [--offset 0] [--id captions]

As a library (tools/build.py): write_captions(project, words, cues, style=..., brand=...).

Styles (all seek-safe GSAP, one paused timeline, highlight exactly at each word's start):
  kinetic  cue words slam in one by one (scale 1.35 -> 1), the current word in the accent colour
  pill     karaoke pill: the whole cue visible, words darken as they are spoken
  pop      the whole cue visible in white, the current word pops (scale 1.08) in the accent colour
Fonts: one family that covers Devanagari AND Latin (default Mukta ExtraBold; Baloo 2, Hind and
Noto Sans Devanagari work too), shipped into <project>/assets/fonts with an in-template @font-face.
Position: inside the Reels safe zone (clear of the top 220 px, bottom 400 px and right 120 px
at 1080x1920); scaled for other canvas sizes. Cues come from tools/captions.py (never overlap).
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

FONTS = {  # family -> (library dir, file, css weight)
    "Mukta": ("mukta", "Mukta-ExtraBold.ttf", 800),
    "Baloo 2": ("baloo2", "Baloo2[wght].ttf", "400 800"),
    "Hind": ("hind", "Hind-Bold.ttf", 700),
    "Noto Sans Devanagari": ("notosansdevanagari", "NotoSansDevanagari[wdth,wght].ttf", "100 900"),
    "Montserrat": ("montserrat", "Montserrat[wght].ttf", "100 900"),
    "Anton": ("anton", "Anton-Regular.ttf", 400),
}


def ship_font(project: Path, family: str) -> str:
    lib, fname, weight = FONTS[family]
    src = cfg.path("fonts") / lib / fname
    safe = fname.replace("[", "_").replace("]", "_").replace(",", "_")
    dst = project / "assets" / "fonts" / safe
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        shutil.copy(src, dst)
    return f'@font-face {{ font-family: "{family}"; src: url("assets/fonts/{safe}") format("truetype"); font-weight: {weight}; }}'


def write_captions(project: Path, words: list[dict], cues: list[dict], *, comp_id: str = "captions",
                   style: str = "kinetic", width: int = 1080, height: int = 1920, offset: float = 0.0,
                   duration: float | None = None, font: str = "Mukta", fg: str = "#F4F0E8",
                   accent: str = "#FFB830", pill_bg: str = "#F4F0E8", ink: str = "#0C0C0E",
                   size: int | None = None, bottom: int | None = None,
                   sides: tuple[int, int] | None = None) -> dict:
    """Write <project>/compositions/<comp_id>.html. Word/cue times are shifted by `offset` s.
    Returns the host-slot attributes to paste into index.html."""
    project = Path(project)
    face = ship_font(project, font)
    s = width / 1080 if width < height else height / 1080   # scale relative to a 1080-wide portrait
    fs = size or round((104 if style == "kinetic" else 76) * s)
    # safe zone: Reels 1080x1920 -> left 90, right 120, bottom 400; captions sit in the lower third
    left, right = (sides[0] + round(30 * s), sides[1]) if sides else (round(90 * s), round(120 * s))
    if bottom is None:
        bottom = round((560 if height > width else 120) * s)
    W = [{"t": html.escape(w["text"]), "s": round(w["start"] + offset, 3), "e": round(w["end"] + offset, 3)}
         for w in words]
    C = [{"s": round(c["start"] + offset, 3), "e": round(c["end"] + offset, 3), "w": c["words"]} for c in cues]
    dur = duration or (max([c["e"] for c in C] + [0]) + 0.5)
    pid = comp_id  # id prefix: unique across the assembled page
    css = f"""
      {face}
      #root {{ position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }}
      #{pid}-stage {{ position: absolute; left: {left}px; width: {width - left - right}px; bottom: {bottom}px; height: {round(fs * 3)}px;
        display: flex; align-items: center; justify-content: center; }}
      .{pid}-cue {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
        flex-wrap: wrap; align-content: center; gap: {round(fs * 0.12)}px {round(fs * 0.34)}px; opacity: 0;
        max-width: {width - left - right}px; text-align: center; }}
      .{pid}-w {{ display: inline-block; font-family: "{font}", sans-serif; font-weight: 800; font-size: {fs}px;
        line-height: 1.25; color: {fg}; white-space: nowrap;
        text-shadow: 0 {round(4 * s)}px {round(18 * s)}px rgba(0,0,0,.55); -webkit-text-stroke: {max(1, round(2 * s))}px rgba(0,0,0,.35);
        paint-order: stroke fill; }}"""
    if style == "pill":
        css += f"""
      .{pid}-cue {{ background: {pill_bg}; border-radius: {round(26 * s)}px; padding: {round(12 * s)}px {round(36 * s)}px {round(18 * s)}px;
        inset: auto; position: absolute; box-shadow: 0 {round(6 * s)}px {round(24 * s)}px rgba(0,0,0,.35); }}
      .{pid}-w {{ color: #6E6E6E; text-shadow: none; -webkit-text-stroke: 0; }}"""
    script = f"""
      var W = {json.dumps(W, ensure_ascii=False)};
      var C = {json.dumps(C)};
      var STYLE = {json.dumps(style)}, FG = {json.dumps(fg)}, ACC = {json.dumps(accent)}, INK = {json.dumps(ink)};
      var stage = document.getElementById("{pid}-stage");
      C.forEach(function (c, ci) {{
        var g = document.createElement("div"); g.id = "{pid}-c" + ci; g.className = "{pid}-cue";
        c.w.forEach(function (wi) {{
          var s = document.createElement("span"); s.id = "{pid}-w" + wi; s.className = "{pid}-w";
          s.innerHTML = W[wi].t; g.appendChild(s);
        }});
        stage.appendChild(g);
      }});
      var tl = gsap.timeline({{ paused: true }});
      C.forEach(function (c, ci) {{
        var g = "#{pid}-c" + ci;
        tl.set(g, {{ opacity: 1 }}, c.s);
        tl.set(g, {{ opacity: 0 }}, c.e);
        c.w.forEach(function (wi, k) {{
          var el = "#{pid}-w" + wi, t = W[wi].s;
          if (STYLE === "kinetic") {{
            tl.set(el, {{ opacity: 0, scale: 1.35, color: FG }}, c.s);
            tl.to(el, {{ opacity: 1, scale: 1, duration: 0.12, ease: "power3.out" }}, t);
            tl.set(el, {{ color: ACC }}, t);
            var nxt = k + 1 < c.w.length ? W[c.w[k + 1]].s : c.e;
            tl.set(el, {{ color: FG }}, nxt);
          }} else if (STYLE === "pill") {{
            tl.set(el, {{ color: "#6E6E6E" }}, c.s);
            tl.to(el, {{ color: INK, duration: 0.06, ease: "none" }}, t);
          }} else {{
            tl.set(el, {{ color: FG, scale: 1 }}, c.s);
            tl.to(el, {{ color: ACC, scale: 1.08, duration: 0.08, ease: "power2.out" }}, t);
            var nx = k + 1 < c.w.length ? W[c.w[k + 1]].s : c.e;
            tl.to(el, {{ color: FG, scale: 1, duration: 0.08, ease: "power2.in" }}, Math.max(t + 0.08, nx - 0.02));
          }}
        }});
      }});
      window.__timelines["{comp_id}"] = tl;"""
    doc = f"""<!doctype html>
<html>
  <head><meta charset="UTF-8" /></head>
  <body>
    <template>
      <style>{css}
      </style>
      <div id="root" data-composition-id="{comp_id}" data-width="{width}" data-height="{height}" data-duration="{round(dur, 3)}">
        <div id="{pid}-stage"></div>
      </div>
      <script>{script}
      </script>
    </template>
  </body>
</html>
"""
    out = project / "compositions" / f"{comp_id}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return {"id": comp_id, "data-composition-id": comp_id, "data-composition-src": f"compositions/{comp_id}.html",
            "data-start": 0, "data-duration": round(dur, 3), "data-width": width, "data-height": height,
            "file": str(out)}


def host_slot(slot: dict, track: int = 10) -> str:
    return (f'<div id="{slot["id"]}-host" class="clip" data-track-kind="captions" '
            f'data-composition-id="{slot["data-composition-id"]}" '
            f'data-composition-src="{slot["data-composition-src"]}" data-start="{slot["data-start"]}" '
            f'data-duration="{slot["data-duration"]}" data-track-index="{track}" '
            f'data-width="{slot["data-width"]}" data-height="{slot["data-height"]}"></div>')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path, help="analysis/<id>/transcript.json or a vo.json")
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--style", default="kinetic", choices=["kinetic", "pill", "pop"])
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--id", default="captions")
    ap.add_argument("--font", default="Mukta", choices=sorted(FONTS))
    ap.add_argument("--size", type=int, default=None, help="canvas WxH, e.g. 1080x1920 (default: portrait)")
    a = ap.parse_args()
    import captions
    d = json.loads(a.src.read_text(encoding="utf-8"))
    if "lines" in d:  # vo.json: lines back to back
        words, t = [], 0.0
        for l in d["lines"]:
            words += [{**w, "start": w["start"] + t, "end": w["end"] + t} for w in l["words"]]
            t += l["duration"]
    else:
        words = d["words"]
    cues = d.get("cues") or captions.build_cues(words)
    w, h = (int(x) for x in (a.size or "1080x1920").split("x"))
    slot = write_captions(a.project, words, cues, comp_id=a.id, style=a.style, width=w, height=h,
                          offset=a.offset, font=a.font)
    print(f"wrote {slot['file']}\nhost slot:\n  {host_slot(slot)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

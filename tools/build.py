"""Build a video: projects/<slug>/edl.json -> processed footage + mix + HyperFrames page (+ draft render).

Usage:  uv run tools/build.py projects/<slug> [--render] [--name draft] [--format feed45] [--quality draft]
        uv run tools/build.py projects/<slug> --dry-run      (resolve + validate only)

Steps (all cached; a re-build redoes only what changed):
 1. validate the EDL, analyse the music (tools/analyze_audio.py, cached)
 2. voiceover lines (tools/voiceover.py) and caption words on the timeline
 3. resolve the timeline: snap cuts to beats/kicks/words (tools/snap.py), frame-round, handles
 4. prepare every clip (tools/prep.py): trim, speed/ramp (RIFE), reframe, grade, keyframes
 5. mix the soundtrack (tools/mix.py): music bed + rides, VO, clip sound, SFX, ducking, -14 LUFS
 6. write index.html: scenes (video/photo/colour), transitions (CSS, or shader via HyperShader),
    clip fx (zoom punch, shake, push-in), flashes, text (brand fonts, Devanagari aware), captions
    (tools/caption_comp.py), end card (brand kit), one <audio> with the mix
 7. write build.json (the resolved timeline: cut anchors, cues, fonts, assets, models, warnings);
    tools/review.py, tools/export.py and tools/credits.py read it
 8. --render: lint, then `hyperframes render` -> renders/<name>.mp4

--format renders a layout variant (another aspect) into projects/<slug>/variants/<format>/ from
the same EDL: footage is re-framed for the new aspect and text positions adapt to its safe zones.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import edl as E  # noqa: E402
import fonts as F  # noqa: E402

VENDOR = cfg.ROOT / "library" / "vendor"
GSAP = VENDOR / "gsap-3.14.2" / "gsap.min.js"
HYPERSHADER = VENDOR / "shader-transitions-0.8.172" / "shader-transitions.global.js"
DEFAULT_BRAND = {"colors": {"accent": "#FFB830", "paper": "#F4F0E8", "ink": "#0C0C0E"},
                 "fonts": {"display": "Anton", "body": "Montserrat", "devanagari_display": "Mukta",
                           "devanagari_body": "Mukta"},
                 "caption": {"style": "kinetic", "font": "Mukta", "fg": "#F4F0E8", "accent": "#FFB830"}}
TEXT_STYLES = {  # size at 1080 px canvas width (portrait); weight; transform
    "title": {"size": 132, "weight": 400, "role": "display", "upper": True, "track": 0.01},
    "big": {"size": 220, "weight": 400, "role": "display", "upper": True, "track": 0.0},
    "subtitle": {"size": 62, "weight": 600, "role": "body", "upper": False, "track": 0.0},
    "tag": {"size": 44, "weight": 700, "role": "body", "upper": True, "track": 0.12},
    "lower": {"size": 58, "weight": 700, "role": "body", "upper": False, "track": 0.0},
    "quote": {"size": 76, "weight": 400, "role": "serif", "upper": False, "track": 0.0},
    "meme": {"size": 124, "weight": 400, "role": "display", "upper": True, "track": 0.01},   # white + black outline
}


def log(msg: str) -> None:
    print(f"[build] {msg}", flush=True)


# ------------------------------------------------------------------ inputs

def vo_lines(edl: dict, project: Path) -> list[dict]:
    """Generate/cached VO clips and place them on the timeline -> [{id, at, path, words(tl)}]."""
    v = edl.get("vo")
    if not v:
        return []
    import voiceover
    script = json.loads(E.resolve_path(v["script"], project).read_text(encoding="utf-8")) if v.get("script") else v
    man = voiceover.run(script, project / "assets" / "vo")
    place = {l["id"]: l for l in v.get("lines", script.get("lines", []))}
    t = float(v.get("start", 0.5))
    gap = float(v.get("gap", 0.35))
    out = []
    for line in man["lines"]:
        at = float(place.get(line["id"], {}).get("at", t))
        out.append({"id": line["id"], "at": at, "path": str(project / "assets" / "vo" / line["file"]),
                    "duration": line["duration"], "text": line["text"], "lang": line["lang"],
                    "engine": line["engine"], "gain_db": float(place.get(line["id"], {}).get("gain_db", v.get("gain_db", 0))),
                    "words": [{**w, "start": round(w["start"] + at, 3), "end": round(w["end"] + at, 3)} for w in line["words"]]})
        t = at + line["duration"] + gap
    return out


def caption_words(edl: dict, project: Path, vo: list[dict], clips: list[dict] | None) -> tuple[list[dict], str | None]:
    """Caption words on the timeline + the engine that produced them."""
    c = edl.get("captions")
    if not c:
        return [w for l in vo for w in l["words"]], None
    src = c.get("src", "vo")
    if src == "vo":
        return [w for l in vo for w in l["words"]], "vo"
    if src == "clips":
        if clips is None:  # before resolving: map through the PLANNED clips (for word snapping)
            import assets
            plan = sorted(edl["clips"], key=lambda c: float(c["at"]))
            words = []
            for k, c in enumerate(plan):
                if "src" not in c or c.get("ramp") or abs(float(c.get("speed", 1)) - 1) > 1e-3:
                    continue
                tp = assets.analysis_dir(E.resolve_path(c["src"], project), create=False) / "transcript.json"
                if not tp.exists():
                    continue
                end = float(plan[k + 1]["at"]) if k + 1 < len(plan) else float(edl.get("duration") or 1e9)
                s0, s1 = float(c.get("in", 0)), float(c.get("in", 0)) + end - float(c["at"])
                shift = float(c["at"]) - s0
                words += [{**w, "start": round(w["start"] + shift, 3), "end": round(w["end"] + shift, 3)}
                          for w in json.loads(tp.read_text(encoding="utf-8"))["words"] if s0 - 0.05 <= w["start"] < s1]
            return sorted(words, key=lambda w: w["start"]), None
        import assets
        words, engine = [], None
        for cl in clips:
            if cl["kind"] != "video" or any(abs(s["speed"] - 1) > 1e-3 for s in cl["segments"]):
                continue
            tp = assets.analysis_dir(Path(cl["path"]), create=False) / "transcript.json"
            if not tp.exists():
                continue
            tr = json.loads(tp.read_text(encoding="utf-8"))
            engine = tr.get("engine")
            s0, s1 = cl["src_in"] + (cl["at"] - cl["tl_start"]), cl["src_in"] + (cl["until"] - cl["tl_start"])
            shift = cl["at"] - s0
            words += [{**w, "start": round(w["start"] + shift, 3), "end": round(w["end"] + shift, 3)}
                      for w in tr["words"] if w["start"] >= s0 - 0.02 and w["end"] <= s1 + 0.05]
        return sorted(words, key=lambda w: w["start"]), engine
    tr = json.loads(E.resolve_path(src, project).read_text(encoding="utf-8"))
    off = float(c.get("offset", 0))
    rng = c.get("range")
    ws = [w for w in tr["words"] if not rng or rng[0] <= w["start"] < rng[1]]
    return [{**w, "start": round(w["start"] + off, 3), "end": round(w["end"] + off, 3)} for w in ws], tr.get("engine")


def safe_zone(W: int, H: int, brand: dict) -> dict:
    """Keep-clear margins in px. 9:16 (Reels/Shorts/TikTok): the platform UI covers the top ~220,
    bottom ~400 and right ~120 px at 1080x1920. 4:5 / 1:1 feed posts: ~6 % margins. 16:9: title-safe."""
    if abs(W / H - 9 / 16) < 0.01:
        k = W / 1080
        z = dict(brand.get("safe_zone_reels") or {"top": 220, "bottom": 400, "right": 120, "left": 60})
        return {kk: round(v * k) for kk, v in z.items()}
    if H >= W:
        m = round(W * 0.06)
        return {"top": m, "bottom": m, "left": m, "right": m}
    return {"top": round(H * 0.07), "bottom": round(H * 0.09), "left": round(W * 0.06), "right": round(W * 0.06)}


def caption_bottom(W: int, H: int, z: dict) -> int:
    """Caption band bottom edge: lower third, above the platform UI."""
    return z["bottom"] + round(H * (0.083 if abs(W / H - 9 / 16) < 0.01 else 0.05))


# ------------------------------------------------------------------ page

def font_for(text: str, role: str, brand: dict, override: str | None) -> tuple[str, bool]:
    """-> (family, italic). Devanagari text always gets a Devanagari-capable family."""
    bf = brand.get("fonts", {})
    if override:
        fam = override
    elif F.is_devanagari(text):
        fam = bf.get("devanagari_display" if role == "display" else "devanagari_body", "Mukta")
    elif role == "serif":
        fam = bf.get("serif_italic", "Playfair Display Italic")
    else:
        fam = bf.get(role, "Anton" if role == "display" else "Montserrat")
    if F.is_devanagari(text) and not F.index().get(fam.replace(" Italic", ""), {}).get("devanagari"):
        fam = "Mukta"
    return fam.replace(" Italic", ""), fam.endswith(" Italic")


class Page:
    def __init__(self, W: int, H: int, fps: float, D: float, project: Path, brand: dict, shader: bool, bg: str):
        self.W, self.H, self.fps, self.D, self.project, self.brand, self.shader, self.bg = W, H, fps, D, project, brand, shader, bg
        self.s = W / 1080 if W < H else H / 1080
        self.faces: dict[tuple, str] = {}
        self.css: list[str] = []
        self.body: list[str] = []
        self.overlays: list[str] = []
        self.js: list[str] = []
        self.track = 0
        self.fonts_used: set[str] = set()
        self.glyphs: list[dict] = []   # (text, font file) pairs for the missing-glyph check
        self.scrims: list[str] = []

    def face(self, family: str, weight: int, italic: bool = False) -> None:
        k = (family, weight, italic)
        if k not in self.faces:
            self.faces[k] = F.face(self.project, family + (" Italic" if italic else ""), weight, italic)
            self.fonts_used.add(family)

    def overlay(self, at: float, dur: float, color: str, peak: float, shape: str = "flash") -> None:
        """A full-frame colour hit: `flash` = peak at `at` then fade; `dip` = fade in to `at`, out after."""
        k = len(self.overlays)
        start = at if shape == "flash" else at - dur / 2
        self.overlays.append(f'<div id="ov{k}" class="clip ovl" style="background-color: {color}" data-start="{round(start, 4)}" '
                             f'data-duration="{round(dur, 4)}" data-track-index="{self.next_track()}"></div>')
        if shape == "flash":
            self.js.append(f'tl.fromTo("#ov{k}", {{opacity: {peak}}}, {{opacity: 0, duration: {round(dur, 4)}, ease: "power2.out"}}, {round(start, 4)});')
        else:
            self.js.append(f'tl.fromTo("#ov{k}", {{opacity: 0}}, {{opacity: {peak}, duration: {round(dur / 2, 4)}, ease: "power1.in"}}, {round(start, 4)});')
            self.js.append(f'tl.to("#ov{k}", {{opacity: 0, duration: {round(dur / 2, 4)}, ease: "power1.out"}}, {round(at, 4)});')

    def highlight(self, k: int, h: dict) -> None:
        """A glowing outline box around something on screen (tutorials): pops in, then pulses gently.
        h = {at, until, box: [x0, y0, x1, y1] in output px, color?}"""
        x0, y0, x1, y1 = (round(v) for v in h["box"])
        col = h.get("color", "#FBBC04")
        pad = round(10 * self.s)
        hid = f"hl{k}"
        dur = round(float(h["until"]) - float(h["at"]), 3)
        self.overlays.append(
            f'<div id="{hid}" class="clip" style="position: absolute; left: {x0 - pad}px; top: {y0 - pad}px; '
            f'width: {x1 - x0 + 2 * pad}px; height: {y1 - y0 + 2 * pad}px; border: {max(4, round(6 * self.s))}px solid {col}; '
            f'border-radius: {round(14 * self.s)}px; box-shadow: 0 0 {round(28 * self.s)}px {col}, inset 0 0 {round(14 * self.s)}px {col}55; '
            f'z-index: 105; pointer-events: none" data-start="{h["at"]}" data-duration="{dur}" data-track-index="{self.next_track()}"></div>')
        self.js.append(f'tl.fromTo("#{hid}", {{scale: 1.35, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.35, ease: "back.out(2)"}}, {h["at"]});')
        reps = max(0, int((dur - 0.6) / 0.7) - 1)
        if reps:
            self.js.append(f'tl.to("#{hid}", {{scale: 1.04, duration: 0.7, ease: "sine.inOut", repeat: {reps}, yoyo: true}}, {round(float(h["at"]) + 0.4, 3)});')

    def next_track(self) -> int:
        self.track += 1
        return self.track

    # scenes ------------------------------------------------------------
    def scene(self, i: int, c: dict, media: str | None) -> None:
        # 0.5 ms early / 1 ms long: a start written as 5.0667 must not miss the frame at 5.06667
        start = round(c["tl_start"] - 0.0005, 4)
        dur = round(c["tl_end"] - c["tl_start"] + 0.001, 4)
        bgc = c.get("color") or self.bg
        st = f' style="background-color: {bgc}"' if self.shader else ""  # CSS mode: only the timed element paints
        if c["kind"] == "video":
            dim = f' style="filter: brightness({1 - float(c["dim"]):.2f})"' if c.get("dim") else ""
            el = (f'<video id="v{i}" class="clip media"{dim} src="{media}" muted playsinline data-start="{start}" '
                  f'data-duration="{dur}" data-track-index="{self.next_track()}"></video>')
        elif c["kind"] == "photo":
            dim = f' style="filter: brightness({1 - float(c["dim"]):.2f})"' if c.get("dim") else ""
            el = (f'<img id="p{i}" class="clip media"{dim} src="{media}" alt="" data-start="{start}" '
                  f'data-duration="{dur}" data-track-index="{self.next_track()}" />')
        else:
            el = (f'<div id="p{i}" class="clip media" style="background-color: {bgc}" data-start="{start}" '
                  f'data-duration="{dur}" data-track-index="{self.next_track()}"></div>')
        self.body.append(f'<div id="s{i}" class="scene"{st}><div id="fx{i}" class="fx"><div id="kb{i}" class="kb">'
                         f'{el}</div></div></div>')

    def text(self, k: int, t: dict) -> None:
        sty = dict(TEXT_STYLES.get(t.get("style", "title"), TEXT_STYLES["title"]))
        content = t["content"]
        fam, ital = font_for(content, sty["role"], self.brand, t.get("font"))
        deva = F.is_devanagari(content)
        weight = int(t.get("weight", 800 if deva and sty["role"] == "display" else sty["weight"]))
        self.face(fam, weight, ital)
        self.glyphs.append({"text": content, "font": fam, "file": str(F.pick(fam, weight, ital)[0])})
        size = round(float(t.get("size", sty["size"] * (0.82 if deva and sty["role"] == "display" else 1))) * self.s)
        col = t.get("color") or self.brand["colors"].get("paper", "#F4F0E8")
        acc = self.brand["colors"].get("accent", "#FFB830")
        z = safe_zone(self.W, self.H, self.brand)
        pos = t.get("pos", "center")
        top = {"top": z["top"] + round(40 * self.s), "center": None,
               "bottom": None, "lower": None}.get(pos)
        css = [f"left: {z['left'] + round(20 * self.s)}px", f"right: {z['right'] + round(20 * self.s)}px"]
        if pos == "top":
            css.append(f"top: {top}px")
        elif pos == "bottom":
            css.append(f"bottom: {z['bottom'] + round(30 * self.s)}px")
        elif pos == "lower":
            css.append(f"bottom: {z['bottom'] + round(260 * self.s)}px")
        elif pos == "abs":
            css.append(f"top: {round(float(t['top']))}px")
        else:
            css += ["top: 0", "bottom: 0"]
        align = "flex-start" if pos == "lower" else "center"
        tx_upper = sty["upper"] and not deva and t.get("upper", True)
        words = content.split()
        hl = set(t.get("highlight", []))
        spans = " ".join(
            f'<span class="w"{" style=" + chr(34) + "color: " + acc + chr(34) if (w.strip(".,!?") in hl or i in hl) else ""}>'
            f'{html.escape(w)}</span>' for i, w in enumerate(words))
        box = ""
        if t.get("style") == "tag":
            box = f"background: {t.get('bg', acc)}; color: {t.get('color') or self.brand['colors'].get('ink', '#0C0C0E')}; padding: {round(10 * self.s)}px {round(26 * self.s)}px; border-radius: {round(8 * self.s)}px;"
        elif t.get("style") == "lower":
            box = f"border-left: {round(10 * self.s)}px solid {acc}; padding-left: {round(26 * self.s)}px;"
        shadow = "" if t.get("style") == "tag" else f"text-shadow: 0 {round(4 * self.s)}px {round(24 * self.s)}px rgba(0,0,0,.6);"
        if t.get("style") == "meme":  # classic meme lettering: white fill, thick black outline
            col = t.get("color") or "#FFFFFF"
            shadow = (f"-webkit-text-stroke: {max(3, round(10 * self.s))}px #000000; paint-order: stroke fill; "
                      f"text-shadow: 0 {round(5 * self.s)}px 0 #000000;")
        if t.get("rotate"):  # sticker tilt (CSS rotate: separate from the GSAP transforms on the words)
            box += f" display: inline-block; rotate: {float(t['rotate'])}deg;"
        dur = round(float(t.get("until", t["at"] + 2.5)) - float(t["at"]), 3)
        tid = f"tx{k}"
        self.overlays.append(
            f'<div id="{tid}" class="clip txt" style="{"; ".join(css)}; justify-content: {align}; text-align: {"left" if pos == "lower" else "center"}" '
            f'data-start="{t["at"]}" data-duration="{dur}" data-track-index="{self.next_track()}">'
            f'<span class="tx-in" style="display: block; font-family: &quot;{fam}&quot;, sans-serif; font-weight: {weight}; '
            f'{"font-style: italic; " if ital else ""}font-size: {size}px; line-height: {1.3 if deva else 1.06}; color: {col}; '
            f'letter-spacing: {0 if deva else sty["track"]}em; {"text-transform: uppercase; " if tx_upper else ""}{shadow}{box}">{spans}</span></div>')
        anim = t.get("anim", "rise")
        at = float(t["at"])
        sel = f"#{tid} .w"
        if anim == "slam":
            self.js.append(f'tl.fromTo("{sel}", {{scale: 1.7, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.2, ease: "power4.out", stagger: 0.07}}, {at});')
        elif anim == "pop":
            self.js.append(f'tl.fromTo("{sel}", {{scale: 0.6, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.28, ease: "back.out(2.2)", stagger: 0.09}}, {at});')
        elif anim == "fade":
            self.js.append(f'tl.fromTo("#{tid} .tx-in", {{opacity: 0}}, {{opacity: 1, duration: 0.45, ease: "power1.out"}}, {at});')
        elif anim == "type":
            self.js.append(f'tl.fromTo("{sel}", {{opacity: 0}}, {{opacity: 1, duration: 0.01, stagger: {float(t.get("stagger", 0.12))}}}, {at});')
        elif anim == "words":  # each word appears exactly at its own time (e.g. synced to VO)
            for i, wt in enumerate(t.get("word_times", [])):
                self.js.append(f'tl.fromTo("#{tid} .w:nth-child({i + 1})", {{opacity: 0, y: {round(30 * self.s)}}}, {{opacity: 1, y: 0, duration: 0.18, ease: "power3.out"}}, {wt});')
        elif anim != "none":  # rise
            self.js.append(f'tl.fromTo("{sel}", {{y: {round(60 * self.s)}, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.5, ease: "power3.out", stagger: 0.06}}, {at});')
        if t.get("out") == "fade":
            self.js.append(f'tl.to("#{tid} .tx-in", {{opacity: 0, duration: 0.25, ease: "power1.in"}}, {round(at + dur - 0.25, 3)});')


def _rgba(hexcol: str, alpha: float) -> str:
    h = hexcol.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def endcard(page: Page, ec: dict, brand: dict) -> list[str]:
    """Brand end card: one timed overlay, lines in a centred column (long names wrap safely).
    anim "epic" (default): the name slams in word by word, the accent rule draws itself, the details
    rise in with a blur, the handle pops, an accent glow pulses behind and the card slowly pushes in.
    anim "simple": everything rises in."""
    import brand as B
    lang = ec.get("lang")
    tpl = (brand.get(f"end_card_{lang}") if lang else None) or brand.get("end_card", {})
    lines = ec.get("lines") or [B.fill(l, brand) for l in tpl.get("lines", [])]
    lines = [l for l in lines if l.strip()]
    at, until = float(ec["at"]), float(ec.get("until", page.D))
    dur = until - at
    col = brand["colors"]
    acc = col.get("accent", "#FFB830")
    z = safe_zone(page.W, page.H, brand)
    s_ = page.s
    spans, n_words = [], 0
    for i, line in enumerate(lines):
        first, handle = i == 0, line.startswith("@")
        role = "display" if first else "body"
        fam, ital = font_for(line, role, brand, None)
        deva = F.is_devanagari(line)
        weight = 800 if (first and deva) else (400 if first else (700 if handle else 600))
        page.face(fam, weight, ital)
        page.glyphs.append({"text": line, "font": fam, "file": str(F.pick(fam, weight, ital)[0])})
        size = round((104 if first else (58 if handle else 50)) * s_ * (0.85 if first and deva else 1))
        style = (f'display: block; font-family: &quot;{fam}&quot;, sans-serif; font-weight: {weight}; font-size: {size}px; '
                 f'line-height: {1.25 if deva else 1.08}; color: {acc if handle else col.get("paper", "#F4F0E8")}; '
                 f'margin-bottom: {round((34 if first else 16) * s_)}px; '
                 + ("text-transform: uppercase; letter-spacing: 0.01em; " if first and not deva else ""))
        cls = "ec-l ec-name" if first else ("ec-l ec-handle" if handle else "ec-l ec-line")
        if first:  # word spans so the name can slam in word by word
            words = line.split()
            n_words = len(words)
            inner = " ".join(f'<span class="ec-w" style="display: inline-block;">{html.escape(w)}</span>' for w in words)
        else:
            inner = html.escape(line)
        spans.append(f'<span class="{cls}" style="{style}">{inner}</span>')
    rule = round(140 * s_)
    spans.insert(1, f'<span class="ec-l ec-rule" style="display: block; width: {rule}px; height: {max(4, round(8 * s_))}px; '
                    f'background-color: {acc}; margin: 0 auto {round(30 * s_)}px;"></span>')
    gsz = round(1000 * s_)
    glow = (f'<span class="ec-glow" style="position: absolute; left: 50%; top: 46%; width: {gsz}px; height: {gsz}px; '
            f'margin-left: -{gsz // 2}px; margin-top: -{gsz // 2}px; border-radius: 50%; '
            f'background: radial-gradient(circle, {_rgba(acc, 0.30)} 0%, {_rgba(acc, 0.10)} 38%, {_rgba(acc, 0)} 68%);"></span>')
    page.overlays.append(
        f'<div id="endcard" class="clip" style="position: absolute; inset: 0; z-index: 130; overflow: hidden; '
        f'background-color: {col.get("ink", "#0C0C0E")}; display: flex; justify-content: center; align-items: center; '
        f'text-align: center; padding: {z["top"]}px {z["right"] + round(30 * s_)}px {z["bottom"]}px {z["left"] + round(30 * s_)}px" '
        f'data-start="{at}" data-duration="{round(dur, 3)}" data-track-index="{page.next_track()}">{glow}'
        f'<span class="ec-in" style="position: relative; display: flex; flex-direction: column; align-items: center;">'
        f'{"".join(spans)}</span></div>')
    J = page.js.append
    J(f'tl.fromTo("#endcard", {{opacity: 0}}, {{opacity: 1, duration: 0.3, ease: "power1.out"}}, {at});')
    if ec.get("anim", "epic") == "simple":
        J(f'tl.fromTo("#endcard .ec-l", {{y: {round(50 * s_)}, opacity: 0}}, {{y: 0, opacity: 1, duration: 0.5, '
          f'ease: "power3.out", stagger: 0.16}}, {round(at + 0.2, 3)});')
        return lines
    t_name = at + 0.12
    t_rule = t_name + 0.12 * max(1, n_words) + 0.12
    t_lines = t_rule + 0.3
    n_lines = sum(1 for l in lines[1:] if not l.startswith("@"))
    t_handle = t_lines + 0.18 * n_lines + 0.15
    # slow push-in of the whole card and a breathing accent glow
    J(f'tl.fromTo("#endcard .ec-in", {{scale: 1}}, {{scale: 1.05, duration: {round(dur, 3)}, ease: "none"}}, {at});')
    J(f'tl.fromTo("#endcard .ec-glow", {{scale: 0.5, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.8, ease: "power2.out"}}, {round(at + 0.05, 3)});')
    reps = max(0, int((dur - 1.0) / 1.1) - 1)
    if reps:
        J(f'tl.to("#endcard .ec-glow", {{scale: 1.18, opacity: 0.65, duration: 1.1, ease: "sine.inOut", repeat: {reps}, yoyo: true}}, {round(at + 0.9, 3)});')
    # the name slams in word by word
    J(f'tl.fromTo("#endcard .ec-w", {{scale: 1.9, opacity: 0, y: {round(-24 * s_)}}}, {{scale: 1, opacity: 1, y: 0, duration: 0.34, '
      f'ease: "power4.out", stagger: 0.12}}, {round(t_name, 3)});')
    # accent rule draws from the centre
    J(f'tl.fromTo("#endcard .ec-rule", {{scaleX: 0}}, {{scaleX: 1, duration: 0.45, ease: "power3.out"}}, {round(t_rule, 3)});')
    # detail lines rise in, de-blurring
    J(f'tl.fromTo("#endcard .ec-line", {{y: {round(40 * s_)}, opacity: 0, filter: "blur(8px)"}}, {{y: 0, opacity: 1, '
      f'filter: "blur(0px)", duration: 0.5, ease: "power3.out", stagger: 0.18}}, {round(t_lines, 3)});')
    # handle pops with a bounce, then one friendly pulse
    J(f'tl.fromTo("#endcard .ec-handle", {{scale: 0.4, opacity: 0}}, {{scale: 1, opacity: 1, duration: 0.55, '
      f'ease: "back.out(2.6)"}}, {round(t_handle, 3)});')
    J(f'tl.to("#endcard .ec-handle", {{scale: 1.1, duration: 0.25, ease: "power2.out", yoyo: true, repeat: 1}}, {round(t_handle + 0.9, 3)});')
    page.end_card_times = {"name": t_name, "rule": t_rule, "lines": t_lines, "handle": t_handle}
    return lines


def write_index(page: Page, tl: dict, shader_transitions: list[dict], captions_slot: str | None, mix_rel: str | None) -> Path:
    p = page.project
    (p / "assets" / "vendor").mkdir(parents=True, exist_ok=True)
    shutil.copy(GSAP, p / "assets" / "vendor" / "gsap.min.js")
    scripts = '<script src="assets/vendor/gsap.min.js"></script>'
    if page.shader:
        shutil.copy(HYPERSHADER, p / "assets" / "vendor" / "shader-transitions.global.js")
        scripts += '\n    <script src="assets/vendor/shader-transitions.global.js"></script>'
    W, H, D = page.W, page.H, page.D
    faces = "\n      ".join(page.faces.values())
    css = f"""
      {faces}
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: {W}px; height: {H}px; overflow: hidden; background: {page.bg}; }}
      #root {{ width: {W}px; height: {H}px; position: relative; overflow: hidden; background-color: {page.bg}; }}
      .scene {{ position: absolute; inset: 0; width: {W}px; height: {H}px; overflow: hidden; }}
      .fx, .kb {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
      .media {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}
      .txt {{ position: absolute; display: flex; align-items: center; z-index: 110; pointer-events: none; }}
      .txt .w {{ display: inline-block; }}
      .ec {{ z-index: 130; }}
      .ovl {{ position: absolute; inset: 0; opacity: 0; z-index: 100; pointer-events: none; }}
      .scrim {{ position: absolute; left: 0; right: 0; z-index: 105; pointer-events: none; }}
      #captions-host {{ position: absolute; inset: 0; z-index: 115; }}
      {"".join(page.css)}"""
    scenes_ids = [f"s{i}" for i in range(len(tl["clips"]))]
    if page.shader:
        tl_init = ("var tl = HyperShader.init({ bgColor: " + json.dumps(page.bg) + ", accentColor: "
                   + json.dumps(page.brand["colors"].get("accent", "#FFB830")) + ", scenes: " + json.dumps(scenes_ids)
                   + ", transitions: " + json.dumps(shader_transitions) + " });")
    else:
        tl_init = "var tl = gsap.timeline({ paused: true });"
    body = "\n      ".join(page.body + page.scrims + page.overlays)
    if captions_slot:
        body += "\n      " + captions_slot
    if mix_rel:
        body += (f'\n      <audio id="mix" src="{mix_rel}" data-start="0" data-duration="{D}" '
                 f'data-track-index="{page.next_track() + 100}" data-volume="1"></audio>')
    js = "\n      ".join(page.js)
    doc = f"""<!doctype html>
<html lang="{page.brand.get('lang', 'en')}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={W}, height={H}" />
    {scripts}
    <style>{css}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{D}" data-width="{W}" data-height="{H}">
      {body}
    </div>
    <script>
      window.__timelines = window.__timelines || {{}};
      {tl_init}
      {js}
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
"""
    out = p / "index.html"
    out.write_text(doc, encoding="utf-8")
    return out


# ------------------------------------------------------------------ main build

def scaffold_files(project: Path, W: int, H: int) -> None:
    """Minimal HyperFrames project files (same as `hyperframes init`, without the example)."""
    project.mkdir(parents=True, exist_ok=True)
    if not (project / "hyperframes.json").exists():
        (project / "hyperframes.json").write_text(json.dumps({
            "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
            "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
            "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
            "media": {"autoProxy": True}}, indent=2), encoding="utf-8")
    if not (project / "meta.json").exists():
        (project / "meta.json").write_text(json.dumps({"id": project.name, "name": project.name,
                                                        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2),
                                           encoding="utf-8")
    if not (project / "package.json").exists():
        v = "0.8.172"
        (project / "package.json").write_text(json.dumps({"name": project.name.lstrip("_").lower(), "private": True, "type": "module",
                                                           "scripts": {"dev": f"npx --yes hyperframes@{v} preview",
                                                                       "check": f"npx --yes hyperframes@{v} check",
                                                                       "render": f"npx --yes hyperframes@{v} render"}}, indent=2),
                                              encoding="utf-8")


def remux_audio(video: Path, mix: Path, abitrate: str = "192k") -> None:
    """Put our mastered mix back on the render. HyperFrames re-measures true peak after its own AAC
    step and lowers the WHOLE soundtrack when a transient overshoots -1 dBTP (it took a boom-heavy
    mix from -13.9 to -16.8 LUFS), so the render's audio is replaced by mix.wav encoded once."""
    import subprocess
    tmp = video.with_name(video.stem + "_remux.mp4")
    subprocess.run([cfg.ffmpeg(), "-v", "error", "-y", "-i", str(video), "-i", str(mix), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", abitrate, "-ar", "48000", "-shortest", "-movflags", "+faststart",
                    str(tmp)], check=True)
    tmp.replace(video)


def build(project: Path, render: bool = False, name: str = "draft", fmt_override: str | None = None,
          quality: str | None = None, dry_run: bool = False) -> dict:
    t0 = time.time()
    project = Path(project).resolve()
    edl = E.load(project)
    src_project = project
    if fmt_override:
        edl = dict(edl, format=fmt_override)
        project = project / "variants" / fmt_override
        project.mkdir(parents=True, exist_ok=True)
    warnings = E.validate(edl, src_project)
    import brand as B
    brand = B.load(edl["brand"]) if edl.get("brand") else DEFAULT_BRAND
    for k, v in DEFAULT_BRAND.items():
        brand.setdefault(k, v)
    W, H, fps = E.fmt(edl)
    audio = None
    music = edl.get("music")
    if music:
        import analyze_audio
        mpath = E.resolve_path(music["src"], src_project)
        log(f"music analysis {mpath.name}")
        audio = analyze_audio.analyze(mpath, tags=False, hf_check=False, quiet=True)
        if not audio.get("beat_grid_reliable", True) and any((c.get("snap") or {}).get("to") in ("beat", "downbeat")
                                                             for c in edl["clips"]):
            warnings.append("music beat grid is unreliable: beat/downbeat snapping may be off (use kick/hit/onset or phrases)")
    scaffold_files(project, W, H)
    vo = [] if dry_run else vo_lines(edl, src_project)
    if vo:
        log(f"voiceover: {len(vo)} lines")
    words_pre, _ = caption_words(edl, src_project, vo, None)
    tl = E.resolve(edl, src_project, audio, words_pre)
    D = tl["duration"]
    words, cap_engine = caption_words(edl, src_project, vo, tl["clips"])
    if dry_run:
        return {"timeline": tl, "warnings": warnings}

    # 4. footage and photos
    import prep
    media = {}
    clip_audio = []
    for c in tl["clips"]:
        if c["kind"] == "video":
            log(f"prep {c['id']}: video {Path(c['path']).name} {c['src_in']:.2f}-{c['src_out']:.2f}s "
                + "/".join(f"{g['speed']:g}x" for g in c["segments"]))
            media[c["id"]] = prep.prep_video(c, tl, edl, project)
            if c.get("audio"):
                a = prep.prep_audio(c, project)
                if a:
                    g = c["audio"] if isinstance(c["audio"], dict) else {}
                    clip_audio.append({"path": str(a), "at": c["tl_start"], "gain_db": g.get("gain_db", 0),
                                       "normalize": g.get("normalize", True)})
        elif c["kind"] == "photo":
            log(f"prep {c['id']}: photo {Path(c['path']).name}")
            media[c["id"]] = prep.prep_photo(c, tl, edl, project)
            if c.get("upscaled"):
                warnings.append(f"{c['id']}: photo is smaller than the canvas x Ken Burns zoom; it will look soft "
                                f"(upscale with tools/fx.py upscale first)")

    # 5. mix
    import mix as M
    sfx_rows = {r["name"]: r for r in json.loads((cfg.ROOT / "library" / "sfx" / "index.json").read_text(encoding="utf-8"))}
    sfx_spec, sfx_files = [], []
    for s in edl.get("sfx", []):
        if "src" in s:
            pth, align = E.resolve_path(s["src"], src_project), s.get("align", "onset")
        else:
            r = sfx_rows.get(s["name"])
            if r is None:
                raise E.EDLError(f"sfx {s['name']!r} not in library/sfx (uv run tools/sfx.py list)")
            pth, align = cfg.ROOT / r["file"], s.get("align", r["align"])
        sfx_files.append(pth)
        sfx_spec.append({"path": str(pth), "at": float(s["at"]), "gain_db": float(s.get("gain_db", 0)), "align": align})
    mspec = None
    if music:
        mspec = {**music, "path": str(E.resolve_path(music["src"], src_project)), "until": music.get("until", D)}
    has_audio = bool(mspec or vo or clip_audio or sfx_spec)
    mix_rel = None
    loud = None
    if has_audio:
        out_wav = project / "assets" / "audio" / "mix.wav"
        out_wav.parent.mkdir(parents=True, exist_ok=True)
        log("mixing soundtrack")
        loud = M.mix({"duration": D, "music": mspec, "vo": vo, "clips": clip_audio, "sfx": sfx_spec,
                      "speech_words": words, "fade_out": edl.get("fade_out", 1.2 if music else 0.3)}, out_wav)
        mix_rel = "assets/audio/mix.wav"

    # 6. page
    bg = edl.get("bg", "#000000")
    page = Page(W, H, fps, D, project, brand, tl["shader_mode"], bg)
    shader_tr = []
    for i, c in enumerate(tl["clips"]):
        rel = media[c["id"]].relative_to(project).as_posix() if c["id"] in media else None
        page.scene(i, c, rel)
        tr = c["transition"]
        typ, d = tr["type"], tr["dur"]
        if i > 0:
            if page.shader:
                f1 = round(1 / fps, 4)
                if typ in E.SHADERS:
                    shader_tr.append({"time": round(c["at"] - d / 2, 4), "shader": typ, "duration": d})
                elif typ == "zoom":
                    shader_tr.append({"time": round(c["at"] - d / 2, 4), "shader": "cinematic-zoom", "duration": d})
                elif typ == "whip":
                    shader_tr.append({"time": round(c["at"] - d / 2, 4), "shader": "whip-pan", "duration": d})
                elif typ == "fade":
                    shader_tr.append({"time": round(c["at"] - d / 2, 4), "duration": d})
                else:
                    shader_tr.append({"time": round(c["at"] - f1, 4), "duration": f1})
            else:
                if typ == "fade":
                    page.js.append(f'tl.fromTo("#fx{i}", {{opacity: 0}}, {{opacity: 1, duration: {d}, ease: "sine.inOut"}}, {c["tl_start"]});')
                elif typ == "zoom":
                    page.js.append(f'tl.fromTo("#fx{i}", {{opacity: 0, scale: 0.86}}, {{opacity: 1, scale: 1, duration: {d}, ease: "power3.out"}}, {c["tl_start"]});')
                    page.js.append(f'tl.to("#fx{i - 1}", {{scale: 1.3, duration: {d}, ease: "power3.in"}}, {c["tl_start"]});')
                elif typ == "whip":
                    page.js.append(f'tl.fromTo("#fx{i}", {{xPercent: 100, filter: "blur(18px)"}}, {{xPercent: 0, filter: "blur(0px)", duration: {d}, ease: "power4.inOut"}}, {c["tl_start"]});')
                    page.js.append(f'tl.to("#fx{i - 1}", {{xPercent: -100, filter: "blur(18px)", duration: {d}, ease: "power4.inOut"}}, {c["tl_start"]});')
            if typ == "flash":
                page.overlay(c["at"], max(d, 0.15), "#FFFFFF", 0.95)
            elif typ == "dip":
                page.overlay(c["at"], max(d, 0.2), "#000000", 1.0, "dip")
        # Ken Burns / push-in on .kb, punches and shake on .fx
        kb = c.get("kenburns")
        if c["kind"] == "photo" and kb is not False:
            kb = kb or {}
            fx_, fy_ = (c.get("focus") or kb.get("focus") or [0.5, 0.5])
            a, b = float(kb.get("from", 1.0)), float(kb.get("to", 1.08))
            page.js.append(f'tl.fromTo("#kb{i}", {{scale: {a}, transformOrigin: "{fx_ * 100:.1f}% {fy_ * 100:.1f}%"}}, '
                           f'{{scale: {b}, duration: {round(c["tl_end"] - c["tl_start"], 3)}, ease: "none"}}, {c["tl_start"]});')
        for f in c.get("fx", []):
            ft = float(f.get("at", c["at"]))
            if f["type"] == "zoom_punch":
                page.js.append(f'tl.set("#fx{i}", {{scale: {f.get("amount", 1.12)}}}, {ft});')
                page.js.append(f'tl.to("#fx{i}", {{scale: 1, duration: {f.get("dur", 0.3)}, ease: "expo.out"}}, {round(ft + 0.001, 4)});')
            elif f["type"] == "scale":  # static tighter framing for the whole clip (jump-cut zoom)
                fo = f.get("origin", [0.5, 0.35])
                page.js.append(f'tl.set("#kb{i}", {{scale: {f.get("amount", 1.15)}, transformOrigin: "{fo[0] * 100:.0f}% {fo[1] * 100:.0f}%"}}, {c["tl_start"]});')
            elif f["type"] in ("push_in", "pull_out"):
                a, b = (1.0, float(f.get("to", 1.1))) if f["type"] == "push_in" else (float(f.get("from", 1.1)), 1.0)
                page.js.append(f'tl.fromTo("#kb{i}", {{scale: {a}}}, {{scale: {b}, duration: {round(c["tl_end"] - c["tl_start"], 3)}, ease: "none"}}, {c["tl_start"]});')
            elif f["type"] == "shake":
                amp, dur = float(f.get("amount", 18)) * page.s, float(f.get("dur", 0.3))
                nfr = max(2, int(dur * fps))
                for k in range(nfr):
                    dec = 1 - k / nfr
                    x = amp * dec * math.sin(k * 2.39 + 0.5)
                    y = amp * 0.7 * dec * math.cos(k * 3.17)
                    page.js.append(f'tl.set("#fx{i}", {{x: {x:.1f}, y: {y:.1f}}}, {round(ft + k / fps, 4)});')
                page.js.append(f'tl.set("#fx{i}", {{x: 0, y: 0}}, {round(ft + nfr / fps, 4)});')
            elif f["type"] == "flash":
                page.overlay(ft, float(f.get("dur", 0.25)), f.get("color", "#FFFFFF"), float(f.get("peak", 0.9)))
    for fl in edl.get("flashes", []):
        page.overlay(float(fl["at"]), float(fl.get("dur", 0.25)), fl.get("color", "#FFFFFF"), float(fl.get("peak", 0.9)))
    for k, t in enumerate(edl.get("text", [])):
        page.text(k, t)
    for k, h in enumerate(edl.get("highlights", [])):
        page.highlight(k, h)
    ec_lines = []
    unconfirmed = []
    if edl.get("endcard"):
        ec_lines = endcard(page, edl["endcard"], brand)
        unconfirmed = list(brand.get("to_confirm", []))
        if unconfirmed:
            warnings.append("end card uses brand facts still to confirm: " + "; ".join(unconfirmed))
    cap_slot, cues = None, []
    if edl.get("captions") is not None and words:
        import caption_comp
        import captions as C
        cc = edl["captions"]
        cues = C.build_cues(words, max_words=int(cc.get("max_words", 3)), max_chars=int(cc.get("max_chars", 22)))
        bc = brand.get("caption", {})
        fam = cc.get("font", bc.get("font", "Mukta"))
        slot = caption_comp.write_captions(project, words, cues, style=cc.get("style", bc.get("style", "kinetic")),
                                           width=W, height=H, duration=D, font=fam,
                                           fg=bc.get("fg", "#F4F0E8"), accent=bc.get("accent", brand["colors"]["accent"]),
                                           size=cc.get("size"), bottom=caption_bottom(W, H, safe_zone(W, H, brand)),
                                           sides=(safe_zone(W, H, brand)["left"], safe_zone(W, H, brand)["right"]))
        page.fonts_used.add(fam)
        lib, fname, _ = caption_comp.FONTS[fam]
        page.glyphs += [{"text": q["text"], "font": fam, "file": str(cfg.path("fonts") / lib / fname)} for q in cues]
        cap_slot = caption_comp.host_slot(slot, track=page.next_track() + 200)
    # legibility: soft dark gradients behind the caption band and top titles (bright photos made
    # white/amber captions unreadable in testing); "scrim": false in the EDL turns them off
    if edl.get("scrim", True):
        if cap_slot or any(t.get("pos") == "bottom" for t in edl.get("text", [])):
            page.scrims.append(f'<div class="scrim" style="bottom: 0; height: {round(H * 0.58)}px; background: '
                               f'linear-gradient(to top, rgba(0,0,0,0.66), rgba(0,0,0,0.5) 62%, rgba(0,0,0,0))"></div>')
        if any(t.get("pos") == "top" for t in edl.get("text", [])):
            page.scrims.append(f'<div class="scrim" style="top: 0; height: {round(H * 0.28)}px; background: '
                               f'linear-gradient(to bottom, rgba(0,0,0,0.66), rgba(0,0,0,0.42) 55%, rgba(0,0,0,0))"></div>')
    idx = write_index(page, tl, shader_tr, cap_slot, mix_rel)

    # 7. build.json
    models = set(edl.get("models", []))
    if vo:
        models.update({"edge-tts" if l["engine"] == "edge-tts" else "kokoro" for l in vo} | {"mms"})
    if cap_engine and cap_engine != "vo":
        e = cap_engine.lower()
        models.update({"indic-flex"} if "flex" in e else {"indic-core"} if "indic" in e else
                      {"parakeet"} if "parakeet" in e else set())
        models.add("mms")
    if any(s["rife"] and s["speed"] < 1 for c in tl["clips"] for s in c["segments"]):
        models.add("rife")
    assets_used = [{"path": c["path"]} for c in tl["clips"] if c.get("path")]
    if music:
        assets_used.append({"path": str(E.resolve_path(music["src"], src_project))})
    assets_used += [{"path": str(p)} for p in sfx_files]
    luts = {prep.grade_name(c, edl) for c in tl["clips"] if c["kind"] != "color"} - {None}
    assets_used += [{"path": str(prep.LUTS / f"{g}.cube")} for g in sorted(luts)]
    text_items = [{"content": t["content"], "at": t["at"], "until": t.get("until", t["at"] + 2.5),
                   "style": t.get("style", "title"), "pos": t.get("pos", "center")} for t in edl.get("text", [])]
    bj = {"title": edl.get("title", src_project.name), "slug": src_project.name, "recipe": edl.get("recipe"),
          "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "format": {"w": W, "h": H, "fps": fps}, "duration": D,
          "shader_mode": tl["shader_mode"], "cuts": [{"clip": k["clip"], "t": k["t"], "planned": k["planned"],
                                                      "anchor": k["anchor"], "kind": k["kind"]} for k in tl["cuts"]],
          "clips": [{k: c.get(k) for k in ("id", "kind", "path", "at", "until", "tl_start", "tl_end", "src_in", "src_out",
                                            "segments", "transition", "fx")} | {"media": str(media.get(c["id"], ""))}
                    for c in tl["clips"]],
          "text": text_items, "endcard": {"lines": ec_lines, **edl.get("endcard", {})} if ec_lines else None,
          "captions": {"cues": [{"start": q["start"], "end": q["end"], "text": q["text"]} for q in cues],
                       "words": words, "engine": cap_engine} if cues else None,
          "vo": [{k: l[k] for k in ("id", "at", "duration", "text", "lang", "engine")} for l in vo],
          "music": {k: v for k, v in (mspec or {}).items() if k != "rides"} or None,
          "sfx": sfx_spec, "loudness": loud, "safe_zone": safe_zone(W, H, brand),
          "fonts": sorted(page.fonts_used), "glyphs": page.glyphs, "models": sorted(models), "assets": assets_used,
          "unconfirmed_facts": unconfirmed, "warnings": warnings, "brand": edl.get("brand"),
          "caption_post": edl.get("caption_post"), "hashtags": edl.get("hashtags", []),
          "build_seconds": round(time.time() - t0, 1)}
    (project / "build.json").write_text(json.dumps(bj, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"index.html written ({len(tl['clips'])} clips, {len(edl.get('text', []))} texts, "
        f"{len(cues)} caption cues, shader mode {tl['shader_mode']}) in {bj['build_seconds']} s")
    for w in warnings:
        log("WARNING: " + w)

    if render:
        import hf
        r = hf.run(["lint"], cwd=project)
        args = ["render", "-o", f"renders/{name}.mp4"]
        if quality:
            args += ["--quality", quality]
        t1 = time.time()
        r = hf.run(args, cwd=project)
        if r.returncode:
            raise SystemExit(f"render failed ({r.returncode})")
        if mix_rel:
            remux_audio(project / "renders" / f"{name}.mp4", project / mix_rel)
        bj["render"] = {"file": str(project / "renders" / f"{name}.mp4"), "seconds": round(time.time() - t1, 1)}
        (project / "build.json").write_text(json.dumps(bj, indent=1, ensure_ascii=False), encoding="utf-8")
        log(f"rendered renders/{name}.mp4 in {bj['render']['seconds']} s")
    return bj


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", type=Path)
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--name", default="draft")
    ap.add_argument("--format", dest="fmt", choices=sorted(E.FORMATS))
    ap.add_argument("--quality", choices=["draft", "looks", "delivery", "standard", "high"])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    try:
        res = build(a.project, a.render, a.name, a.fmt, a.quality, a.dry_run)
    except E.EDLError as e:
        print(f"EDL error: {e}")
        return 2
    if a.dry_run:
        tl = res["timeline"]
        for c in tl["clips"]:
            print(f"{c['id']:<5} {c['kind']:<5} {c['at']:7.3f}-{c['until']:7.3f} tl {c['tl_start']:.3f}-{c['tl_end']:.3f}"
                  f" src {c['src_in']}-{c['src_out']}  {c['transition']['type']}")
        for w in res["warnings"]:
            print("warning:", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())

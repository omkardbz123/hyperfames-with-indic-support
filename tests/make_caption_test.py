"""Build projects/_test-captions: a 9:16 Devanagari pill-karaoke caption render for sync checks.

Usage:  uv run tests/make_caption_test.py [--fixture words_mr]

Uses the aligned words of tests/fixtures/<fixture>.wav (runs tools/transcribe.py with the
fixture's own text), the fixture audio, Mukta from library/fonts, and the logic of HyperFrames'
caption-pill-karaoke (registry component) adapted to 1080x1920 with no highlight lead.
A 48 px sync marker (top-left) flips white/red at every word start on the same timeline;
tests/eval_caption_sync.py measures it in the rendered MP4.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

PROJECT = ROOT / "projects" / "_test-captions"

TEMPLATE = r"""<!doctype html>
<html lang="mr" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      @font-face { font-family: "Mukta"; src: url("assets/fonts/Mukta-ExtraBold.ttf") format("truetype"); font-weight: 800; }
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body { width: 1080px; height: 1920px; overflow: hidden; background: #0c0c0e; }
      #root { width: 100%; height: 100%; position: relative; font-family: "Mukta", sans-serif; }
      #bg { position: absolute; inset: 0; background: radial-gradient(circle at 50% 35%, #2a2418 0%, #0c0c0e 70%); }
      #title { position: absolute; top: 300px; width: 100%; text-align: center; color: #ffb830;
               font-weight: 800; font-size: 84px; }
      #sync-marker { position: absolute; left: 0; top: 0; width: 48px; height: 48px; background: #000; }
      .safe-zone { position: absolute; left: 90px; width: 900px; bottom: 560px; height: 300px;
                   display: flex; align-items: center; justify-content: center; }
      .caption-group { position: absolute; inset: 0; display: flex; align-items: center;
                       justify-content: center; opacity: 0; }
      .caption-pill { padding: 14px 44px 22px; border-radius: 26px; background: #f4f0e8;
                      box-shadow: 0 6px 24px rgba(0,0,0,.35); text-align: center; }
      .caption-line { display: flex; justify-content: center; gap: 22px; white-space: nowrap; max-width: 900px; }
      .caption-word { display: inline-block; color: #a6a6a6; font-weight: 800; font-size: 78px; line-height: 1.3; }
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="__DURATION__"
         data-width="1080" data-height="1920">
      <div id="bg" class="clip" data-start="0" data-duration="__DURATION__" data-track-index="0"></div>
      <div id="title" class="clip" data-start="0" data-duration="__DURATION__" data-track-index="1">कॅप्शन चाचणी</div>
      <div id="captions" class="clip" data-start="0" data-duration="__DURATION__" data-track-index="2">
        <div id="caption-stage" class="safe-zone"></div>
      </div>
      <div id="sync-marker" class="clip" data-start="0" data-duration="__DURATION__" data-track-index="3"></div>
      <audio id="vo" src="assets/__AUDIO__" data-start="0" data-duration="__DURATION__" data-track-index="4"></audio>
    </div>
    <script>
      var DURATION = __DURATION__;
      var CUES = __CUES__;      // pages from tools/captions.py (no overlaps)
      var WORDS = __WORDS__;    // aligned words: {text, start, end}
      var COLOR_INACTIVE = "#A6A6A6", COLOR_ACTIVE = "#0C0C0E", FADE = 0.06;

      var stage = document.getElementById("caption-stage");
      CUES.forEach(function (cue, ci) {
        var g = document.createElement("div"); g.id = "cap-" + ci; g.className = "caption-group";
        var pill = document.createElement("div"); pill.className = "caption-pill";
        var line = document.createElement("div"); line.className = "caption-line";
        cue.words.forEach(function (wi) {
          var s = document.createElement("span"); s.id = "w-" + wi; s.className = "caption-word";
          s.textContent = WORDS[wi].text; line.appendChild(s);
        });
        pill.appendChild(line); g.appendChild(pill); stage.appendChild(g);
      });

      var tl = gsap.timeline({ paused: true });
      tl.fromTo("#title", { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.5 }, 0);
      CUES.forEach(function (cue, ci) {
        var g = document.getElementById("cap-" + ci);
        tl.set(g, { opacity: 1 }, cue.start);
        tl.set(g, { opacity: 0 }, cue.end);
        cue.words.forEach(function (wi) {
          var el = document.getElementById("w-" + wi);
          tl.set(el, { color: COLOR_INACTIVE }, cue.start);
          tl.to(el, { color: COLOR_ACTIVE, duration: FADE, ease: "none" }, WORDS[wi].start);
        });
      });
      WORDS.forEach(function (w, i) {   // sync marker: flips at every word start
        tl.set("#sync-marker", { backgroundColor: i % 2 ? "#ff0000" : "#ffffff" }, w.start);
      });
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fixture", default="words_mr")
    a = ap.parse_args()
    import transcribe
    fx = ROOT / "tests" / "fixtures"
    wav = fx / f"{a.fixture}.wav"
    truth = json.loads((fx / f"{a.fixture}.truth.json").read_text(encoding="utf-8"))
    tr = transcribe.transcribe(wav, truth["language"], text=truth["text"], quiet=True)
    if not PROJECT.exists():
        sys.exit(f"missing {PROJECT}; scaffold it with: uv run tools/hf.py init {PROJECT.name} --example blank "
                 "--resolution portrait --non-interactive  (from projects/)")
    (PROJECT / "assets" / "fonts").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "library" / "fonts" / "mukta" / "Mukta-ExtraBold.ttf", PROJECT / "assets" / "fonts")
    shutil.copy(wav, PROJECT / "assets" / wav.name)
    dur = round(tr["duration"], 3)
    words = [{"text": w["text"], "start": w["start"], "end": w["end"]} for w in tr["words"]]
    html = (TEMPLATE.replace("__DURATION__", str(dur)).replace("__AUDIO__", wav.name)
            .replace("__CUES__", json.dumps(tr["cues"], ensure_ascii=False))
            .replace("__WORDS__", json.dumps(words, ensure_ascii=False)))
    (PROJECT / "index.html").write_text(html, encoding="utf-8")
    (PROJECT / "sync_words.json").write_text(json.dumps({"fixture": a.fixture, "words": words, "truth": truth["words"]},
                                                        indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {PROJECT / 'index.html'}: {len(words)} words, {len(tr['cues'])} cues, {dur} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

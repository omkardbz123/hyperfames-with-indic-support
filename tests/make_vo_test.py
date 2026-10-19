"""Phase 7 acceptance: a Marathi voiceover + Devanagari kinetic captions, rendered in sync.

Usage:  uv run tests/make_vo_test.py [--style kinetic] [--render]

Builds projects/_test-vo: VO lines from tools/voiceover.py placed back to back (0.35 s gaps) as
<audio> clips, the caption sub-composition from tools/caption_comp.py, a background, and a 48 px
sync marker that flips at every word start. Also writes the expected audio track (_ref.wav) and
sync_words.json for tests/eval_caption_sync.py --project projects/_test-vo.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

import audiolib as al  # noqa: E402
import caption_comp  # noqa: E402
import captions  # noqa: E402
import voiceover  # noqa: E402

PROJ = ROOT / "projects" / "_test-vo"
GAP, LEAD = 0.35, 0.5
SCRIPT = {"lang": "mr", "voice": "mr_f", "lines": [
    {"id": "l01", "text": "प्राणी आपल्यासारखेच वेदना अनुभवतात."},
    {"id": "l02", "text": "त्यांच्या स्वातंत्र्यासाठी, या रविवारी पणजीत आमच्यासोबत चाला.", "voice": "mr_m"},
    {"id": "l03", "text": "गोवा प्राणी मुक्ती मोर्चा. सकाळी नऊ वाजता, आझाद मैदान."},
]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--style", default="kinetic", choices=["kinetic", "pill", "pop"])
    ap.add_argument("--render", action="store_true")
    a = ap.parse_args()
    if not (PROJ / "hyperframes.json").exists():
        subprocess.run([sys.executable, str(ROOT / "tools" / "hf.py"), "init", PROJ.name, "--example", "blank",
                        "--resolution", "portrait", "--non-interactive"], cwd=PROJ.parent, check=True,
                       capture_output=True)
    vo = voiceover.run(SCRIPT, PROJ / "assets" / "vo")
    words, audio_tags, t = [], [], LEAD
    ref = np.zeros(int(48000 * (LEAD + vo["total_duration"] + GAP * len(vo["lines"]) + 1)), np.float32)
    for i, l in enumerate(vo["lines"]):
        words += [{**w, "start": round(w["start"] + t, 3), "end": round(w["end"] + t, 3)} for w in l["words"]]
        audio_tags.append(f'<audio id="vo{i}" src="assets/vo/{l["file"]}" data-start="{t:.3f}" '
                          f'data-duration="{l["duration"]:.3f}" data-track-index="{20 + i}"></audio>')
        al.place(ref[:, None], al.decode(PROJ / "assets" / "vo" / l["file"], 48000, 1), t, sr=48000)
        t += l["duration"] + GAP
    dur = round(t + 0.6, 3)
    cues = captions.build_cues(words, max_words=3)
    slot = caption_comp.write_captions(PROJ, words, cues, style=a.style, duration=dur)
    al.write_wav(PROJ / "_ref.wav", ref[: int(dur * 48000)], 48000)
    marker = json.dumps([w["start"] for w in words])
    (PROJ / "index.html").write_text(f"""<!doctype html>
<html lang="mr" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ width: 1080px; height: 1920px; overflow: hidden; background: #0c0c0e; }}
      #root {{ width: 100%; height: 100%; position: relative; }}
      #bg {{ position: absolute; inset: 0; background: radial-gradient(circle at 50% 30%, #3a2a10 0%, #0c0c0e 70%); }}
      #sync-marker {{ position: absolute; left: 0; top: 0; width: 48px; height: 48px; background: #000; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{dur}" data-width="1080" data-height="1920">
      <div id="bg" class="clip" data-start="0" data-duration="{dur}" data-track-index="0"></div>
      {caption_comp.host_slot(slot, track=10)}
      <div id="sync-marker" class="clip" data-start="0" data-duration="{dur}" data-track-index="11"></div>
      {chr(10).join('      ' + x for x in audio_tags)}
    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      {marker}.forEach(function (t, i) {{ tl.set("#sync-marker", {{ backgroundColor: i % 2 ? "#ff0000" : "#ffffff" }}, t); }});
      window.__timelines["main"] = tl;
      tl.seek(0);
    </script>
  </body>
</html>
""", encoding="utf-8")
    (PROJ / "sync_words.json").write_text(json.dumps({"reference": "_ref.wav", "words": words, "truth": words,
                                                      "note": "truth = MMS alignment of the generated VO"},
                                                     indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"built {PROJ}: {len(vo['lines'])} VO lines, {len(words)} words, {len(cues)} cues, {dur} s, style {a.style}")
    if a.render:
        import hf
        p = hf.run(["render", "-o", "renders/captions.mp4"], cwd=PROJ)
        return p.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())

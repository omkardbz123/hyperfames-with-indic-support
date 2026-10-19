"""audiomap.json for the /music-to-video skill, with timing from our audio.json.

Usage:  uv run tools/audiomap.py <music file> -o projects/<slug>/audiomap.json [--from 12.0 --dur 20]

The skill's analyze-beatgrid.py gives useful structure (energy phases, rolls, key moments, phrases)
but its tempo/grid can be wrong (it halved Go Cart: 57 vs 115 BPM) and its moments are whole
seconds. This runs it, then:
- replaces tempo.bpm, grid.beats_sec and grid.downbeats_sec with audio.json (Beat This!)
- moves every key_moment / hard_stop / silence time to the nearest audio.json hit, drop, kick or
  onset within 0.6 s (keeping the original as `t_coarse`)
- adds a `studio` block: beat_grid_reliable, drops, hits, kicks, snares, sections
With --from/--dur the map covers only that excerpt (times relative to the excerpt start), for a
track trimmed in the edit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

SKILL = cfg.ROOT / ".claude" / "skills" / "music-to-video" / "scripts" / "analyze-beatgrid.py"


def _nearest(t: float, cands: list[float], tol: float) -> float | None:
    best = min(cands, key=lambda a: abs(a - t), default=None)
    return best if best is not None and abs(best - t) <= tol else None


def build(music: Path, out: Path, start: float = 0.0, dur: float | None = None) -> dict:
    import analyze_audio
    a = analyze_audio.analyze(music, tags=False, hf_check=False, quiet=True)
    src = music
    if start or dur:
        src = out.with_name("_excerpt.wav")
        args = [cfg.ffmpeg(), "-v", "error", "-y", "-ss", str(start)] + (["-t", str(dur)] if dur else []) + \
               ["-i", str(music), "-ac", "2", "-ar", "44100", str(src)]
        subprocess.run(args, check=True)
    raw = out.with_name("_audiomap_skill.json")
    subprocess.run([sys.executable, str(SKILL), str(src), "-o", str(raw)], check=True, capture_output=True)
    m = json.loads(raw.read_text(encoding="utf-8"))
    end = start + (dur or a["duration"])
    rel = lambda xs: [round(x - start, 3) for x in xs if start <= x <= end]  # noqa: E731
    on = a.get("onsets", {})
    hits = [h["t"] if isinstance(h, dict) else h for h in a.get("hits", [])]
    drops = list(a.get("drops", []))
    precise = sorted(rel(hits) + rel(drops) + rel(on.get("kick", [])) + rel(on.get("all", [])))
    skill_bpm = m.get("tempo", {}).get("bpm")
    m["tempo"] = {**m.get("tempo", {}), "bpm": a["bpm"], "skill_bpm": skill_bpm, "source": "audio.json (Beat This!)"}
    m["grid"] = {"beats_sec": rel(a.get("beats", [])), "downbeats_sec": rel(a.get("downbeats", []))}
    for key in ("key_moments", "hard_stops", "silences"):
        for item in m.get(key, []):
            if not isinstance(item, dict):
                continue
            for f in ("t", "start", "time"):
                if isinstance(item.get(f), (int, float)):
                    p = _nearest(float(item[f]), precise, 0.6)
                    if p is not None:
                        item[f + "_coarse"], item[f] = item[f], p
    m["studio"] = {"beat_grid_reliable": a.get("beat_grid_reliable"), "drops": rel(drops), "hits": rel(hits),
                   "kicks": rel(on.get("kick", [])), "snares": rel(on.get("snare", [])),
                   "sections": [{**s, "start": round(s["start"] - start, 3), "end": round(s["end"] - start, 3)}
                                for s in a.get("sections", []) if s["end"] > start and s["start"] < end],
                   "note": "timing source of truth is audio.json; tempo/grid/moments were corrected from it"}
    out.write_text(json.dumps(m, indent=1), encoding="utf-8")
    raw.unlink()
    if src != music:
        src.unlink()
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("music", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--from", dest="start", type=float, default=0.0)
    ap.add_argument("--dur", type=float)
    a = ap.parse_args()
    m = build(a.music, a.out, a.start, a.dur)
    print(f"audiomap -> {a.out}: {m['tempo']['bpm']} BPM (skill said {m['tempo']['skill_bpm']}), "
          f"{len(m['grid']['beats_sec'])} beats, {len(m.get('key_moments', []))} key moments, "
          f"grid reliable: {m['studio']['beat_grid_reliable']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

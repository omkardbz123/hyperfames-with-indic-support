"""Score tools/analyze_audio.py against a fixture's ground truth.

Usage:  uv run tests/eval_audio.py [tests/fixtures/beat_128.wav] [--fresh]
Exit code 1 if any acceptance threshold fails.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()


def prf(est, ref, tol):
    est, ref = np.asarray(est, float), np.asarray(ref, float)
    if not len(est) or not len(ref):
        return 0.0, 0.0, 0.0, None
    used, hits, errs = set(), 0, []
    for r in ref:
        d = np.abs(est - r)
        for j in np.argsort(d):
            if d[j] > tol:
                break
            if j not in used:
                used.add(j)
                hits += 1
                errs.append(est[j] - r)
                break
    p, r = hits / len(est), hits / len(ref)
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f, (float(np.mean(np.abs(errs))) * 1000 if errs else None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", nargs="?", default=str(ROOT / "tests/fixtures/beat_128.wav"))
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    import analyze_audio
    f = Path(a.file)
    truth = json.loads(f.with_suffix(".truth.json").read_text(encoding="utf-8"))
    res = analyze_audio.analyze(f, tags=False, hf_check=False, fresh=a.fresh, quiet=True)

    rows, ok = [], True

    def check(name, value, passed, detail=""):
        nonlocal ok
        ok &= bool(passed)
        rows.append(f"{'PASS' if passed else 'FAIL'}  {name:<22} {value:<28} {detail}")

    check("bpm", f"{res['bpm']} (truth {truth['bpm']})", abs(res["bpm"] - truth["bpm"]) <= 1.0, "±1 BPM")
    p, r, fm, err = prf(res["beats"], truth["beats"], 0.07)
    check("beats F (±70 ms)", f"F {fm:.3f} P {p:.2f} R {r:.2f}", fm >= 0.95,
          f"mean |err| {err:.1f} ms" if err is not None else "")
    check("beat timing", f"{err:.1f} ms" if err is not None else "n/a", err is not None and err <= 15, "≤ 15 ms")
    p, r, fm, err = prf(res["downbeats"], truth["downbeats"], 0.07)
    check("downbeats F (±70 ms)", f"F {fm:.3f} P {p:.2f} R {r:.2f}", fm >= 0.8)
    check("beat grid reliable", str(res["beat_grid_reliable"]), res["beat_grid_reliable"], res["beat_grid"]["reason"])
    for k, tk in (("kick", "kicks"), ("snare", "snares"), ("hihat", "hihats")):
        if tk not in truth:
            continue
        p, r, fm, err = prf(res["onsets"][k], truth[tk], 0.03)
        check(f"{k} F (±30 ms)", f"F {fm:.3f} P {p:.2f} R {r:.2f}", fm >= (0.9 if k != "hihat" else 0.8),
              f"mean |err| {err:.1f} ms" if err is not None else "")
    d_err = min((abs(d - truth["drops"][0]) for d in res["drops"]), default=None)
    check("drop", f"{res['drops']} (truth {truth['drops']})", d_err is not None and d_err <= 0.05, "±50 ms")
    ts = truth["silences"][0]
    inner = [s for s in res["silences"] if s["start"] > 0.05 and s["end"] < res["duration"] - 0.05]
    s_err = min((max(abs(s["start"] - ts["start"]), abs(s["end"] - ts["end"])) for s in inner), default=None)
    check("hard stop edges", f"{[(s['start'], s['end']) for s in inner]}",
          s_err is not None and s_err <= 0.02 and len(inner) == len(truth["silences"]),
          "±20 ms, no extras (lead/tail silence ignored)")
    print(f"{f.name}: analysed in {res['timings_s']['total']} s")
    print("\n".join(rows))
    print("sections:", " | ".join(f"{s['start']}-{s['end']} {s['label']}/{s['role']}" for s in res["sections"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

"""Score stem separation on tests/fixtures/vocalmix.wav (known vocal + instrumental parts).

Usage:  uv run tests/eval_stems.py [--model NAME] [--quality] [--fresh]

Reports SDR (dB) for vocals and instrumental, and the vocal-band (300-3400 Hz) energy of
the separated vocals inside vs outside the spoken span (leakage). Pass: vocals SDR >= 8 dB
and instrumental SDR >= 10 dB, leakage <= -20 dB.
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

import audiolib as al  # noqa: E402
import separate  # noqa: E402

SR = 44100


def sdr(est: np.ndarray, ref: np.ndarray) -> float:
    n = min(len(est), len(ref))
    est, ref = est[:n].astype(np.float64), ref[:n].astype(np.float64)
    return float(10 * np.log10((ref ** 2).sum() / (((ref - est) ** 2).sum() + 1e-12) + 1e-12))


def band_energy_db(x: np.ndarray, lo: float = 300, hi: float = 3400) -> float:
    from scipy.signal import butter, sosfilt
    sos = butter(4, [lo, hi], btype="band", fs=SR, output="sos")
    y = sosfilt(sos, x)
    return float(10 * np.log10(np.mean(y ** 2) + 1e-12))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model")
    ap.add_argument("--quality", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    a = ap.parse_args()
    fx = ROOT / "tests" / "fixtures"
    truth = json.loads((fx / "vocalmix.truth.json").read_text(encoding="utf-8"))
    stems = separate.separate(fx / "vocalmix.wav", quality=a.quality, model=a.model, fresh=a.fresh, quiet=True)
    meta = json.loads((stems["vocals"].parent.parent / "stems.json").read_text(encoding="utf-8"))
    run = next(r for r in meta["runs"].values() if Path(r["stems"]["vocals"]) == stems["vocals"])
    v_ref = al.decode(fx / "vocalmix_vocals.wav", SR, 1)[:, 0]
    i_ref = al.decode(fx / "vocalmix_instrumental.wav", SR, 1)[:, 0]
    v_est = al.decode(stems["vocals"], SR, 1)[:, 0]
    i_est = al.decode(stems["instrumental"], SR, 1)[:, 0]
    s0, s1 = (int(t * SR) for t in truth["vocal_span"])
    pad = int(0.3 * SR)
    inside = band_energy_db(v_est[s0:s1])
    outside = band_energy_db(np.r_[v_est[:max(0, s0 - pad)], v_est[s1 + pad:]])
    v_sdr, i_sdr, leak = sdr(v_est, v_ref), sdr(i_est, i_ref), outside - inside
    ok = v_sdr >= 8 and i_sdr >= 10 and leak <= -20
    print(f"model {Path(run['stems']['vocals']).parent.name}: {run['seconds']} s for {run['audio_seconds']} s "
          f"(RTF {run['rtf']}, {run['device']})")
    print(f"  vocals SDR        {v_sdr:6.1f} dB   (>= 8)")
    print(f"  instrumental SDR  {i_sdr:6.1f} dB   (>= 10)")
    print(f"  vocal-band leakage outside the voice span {leak:6.1f} dB   (<= -20)")
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

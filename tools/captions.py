"""Caption cues from word timings, plus SRT / VTT / HyperFrames-transcript export.

Usage:  uv run tools/captions.py <transcript.json> [--srt out.srt] [--vtt out.vtt]
                                 [--hf projects/<slug>/transcript.json] [--max-words 4]

Cue rules (Reels-friendly pages): at most `max_words` words and `max_chars` characters,
at most `max_dur` s, and a new page after a pause >= `pause` s or after . ! ? । punctuation.
Cues never overlap: a page is held `hold` s after its last word but always ends before the
next page starts (the Goa reel bug was an outgoing page still fading as the next appeared).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

SENTENCE_END = re.compile(r"[.!?।॥]$")


def build_cues(words: list[dict], max_words: int = 4, max_chars: int = 24, max_dur: float = 2.6,
               pause: float = 0.45, hold: float = 0.25) -> list[dict]:
    cues: list[dict] = []
    cur: list[int] = []

    def flush():
        if cur:
            cues.append({"start": words[cur[0]]["start"], "end": words[cur[-1]]["end"],
                         "text": " ".join(words[i]["text"] for i in cur), "words": list(cur)})
            cur.clear()

    for i, w in enumerate(words):
        if cur:
            prev = words[cur[-1]]
            text_len = len(" ".join(words[j]["text"] for j in cur + [i]))
            if (len(cur) >= max_words or text_len > max_chars or w["end"] - words[cur[0]]["start"] > max_dur
                    or w["start"] - prev["end"] >= pause or SENTENCE_END.search(prev["text"])):
                flush()
        cur.append(i)
    flush()
    for k, c in enumerate(cues):
        nxt = cues[k + 1]["start"] if k + 1 < len(cues) else None
        end = c["end"] + hold
        c["end"] = round(min(end, nxt) if nxt is not None else end, 3)
        c["start"] = round(c["start"], 3)
    return cues


def _ts(t: float, sep: str) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(cues: list[dict]) -> str:
    return "\n".join(f"{i}\n{_ts(c['start'], ',')} --> {_ts(c['end'], ',')}\n{c['text']}\n"
                     for i, c in enumerate(cues, 1))


def to_vtt(cues: list[dict]) -> str:
    return "WEBVTT\n\n" + "\n".join(f"{_ts(c['start'], '.')} --> {_ts(c['end'], '.')}\n{c['text']}\n"
                                    for c in cues)


def to_hf_words(words: list[dict]) -> list[dict]:
    """HyperFrames project transcript.json: [{id, text, start, end}]."""
    return [{"id": f"w{i}", "text": w["text"], "start": w["start"], "end": w["end"]} for i, w in enumerate(words)]


def write_exports(tr: dict, srt: Path | None = None, vtt: Path | None = None, hf: Path | None = None) -> None:
    if srt:
        srt.write_text(to_srt(tr["cues"]), encoding="utf-8")
    if vtt:
        vtt.write_text(to_vtt(tr["cues"]), encoding="utf-8")
    if hf:
        hf.parent.mkdir(parents=True, exist_ok=True)
        hf.write_text(json.dumps(to_hf_words(tr["words"]), indent=1, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", type=Path, help="analysis/<id>/transcript.json")
    ap.add_argument("--srt", type=Path)
    ap.add_argument("--vtt", type=Path)
    ap.add_argument("--hf", type=Path, help="write a HyperFrames project transcript.json here")
    ap.add_argument("--max-words", type=int, help="rebuild cues with this page size")
    a = ap.parse_args()
    tr = json.loads(a.transcript.read_text(encoding="utf-8"))
    if a.max_words:
        tr["cues"] = build_cues(tr["words"], max_words=a.max_words)
    write_exports(tr, a.srt, a.vtt, a.hf)
    print(f"{len(tr['words'])} words, {len(tr['cues'])} cues")
    return 0


if __name__ == "__main__":
    sys.exit(main())

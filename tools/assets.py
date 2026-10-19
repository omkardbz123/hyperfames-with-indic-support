"""Asset identity: content-hash IDs and the per-asset analysis cache folder.

Asset id = `<sha1-of-file, first 8 hex>_<sanitised-name>` (BUILD_PLAN §4.3), so analysis is
skipped when the file is unchanged, wherever it lives.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path

import studio_config as cfg


def sha1(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def sanitise(name: str, maxlen: int = 40) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return (s[:maxlen].rstrip("-")) or "asset"


def asset_id(path: str | Path) -> str:
    p = Path(path)
    return f"{sha1(p)[:8]}_{sanitise(p.stem)}"


def analysis_dir(path: str | Path, create: bool = True) -> Path:
    d = cfg.ROOT / "analysis" / asset_id(path)
    if create:
        d.mkdir(parents=True, exist_ok=True)
        meta = d / "asset.json"
        if not meta.exists():
            meta.write_text(json.dumps({"asset_id": d.name, "source": str(Path(path).resolve()),
                                        "sha1": sha1(path),
                                        "registered": time.strftime("%Y-%m-%dT%H:%M:%S")},
                                       indent=1, ensure_ascii=False), encoding="utf-8")
    return d

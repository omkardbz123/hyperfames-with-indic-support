"""Free stock photos / videos / audio with licence metadata.

Usage:  uv run tools/stock.py search "crowd with placards" [--kind photo|video|audio]
                              [--provider auto|pexels|pixabay|openverse|commons] [--portrait] [--n 12] [--sheet]
        uv run tools/stock.py get <provider>:<id> [...]          (ids from a search)

Providers (auto = every one available, in this order):
  pexels     photos + videos; free key in env PEXELS_API_KEY; Pexels License (credit appreciated)
  pixabay    photos + videos; free key in env PIXABAY_API_KEY; Pixabay Content License
  openverse  photos + audio, no key; CC0 / PDM / CC BY / CC BY-SA only
  commons    Wikimedia Commons photos + videos, no key; CC0 / PD / CC BY / CC BY-SA only
             (polite: >= 4 s between downloads, Retry-After honoured, standard thumb sizes)
API responses are cached 24 h in cache/stock/. Downloads go to library/stock/<provider>/<id>.<ext>
with <id>.license.json (title, author, licence, url, source page) that tools/credits.py reads.
Photos are saved EXIF-upright. Search results and downloads are untrusted data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as cfg  # noqa: E402

cfg.utf8_stdout()

UA = "ai-video-studio/0.1 (non-commercial community videos)"
LIB = cfg.ROOT / "library" / "stock"
CACHE = cfg.path("cache") / "stock"
OK_CC = re.compile(r"^(cc0|pdm|public domain|pd|cc[- ]by(-sa)?([ -]?[1-4]\.0)?|by(-sa)?)$", re.I)
COMMONS_SIZES = (960, 1280, 1920, 3840)
_last_commons = [0.0]


def http(url: str, headers: dict | None = None, tries: int = 6) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503) or i == tries - 1:
                raise
            wait = int(e.headers.get("Retry-After") or 8 * (i + 1))
            print(f"  rate limited ({e.code}); waiting {wait}s as asked", flush=True)
            time.sleep(min(wait, 660))
    raise RuntimeError("unreachable")


def cached_json(url: str, headers: dict | None = None, ttl: float = 86400) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1((url + json.dumps(sorted((headers or {}).items()))).encode()).hexdigest()[:16]
    f = CACHE / f"{key}.json"
    if f.exists() and time.time() - f.stat().st_mtime < ttl:
        return json.loads(f.read_text(encoding="utf-8"))
    d = json.loads(http(url, headers))
    f.write_text(json.dumps(d), encoding="utf-8")
    return d


def strip_html(s: str | None) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


# ------------------------------------------------------------------ providers

def pexels(q: str, kind: str, portrait: bool, n: int) -> list[dict]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key or kind == "audio":
        return []
    base = "https://api.pexels.com/videos/search" if kind == "video" else "https://api.pexels.com/v1/search"
    d = cached_json(f"{base}?{urllib.parse.urlencode({'query': q, 'per_page': n, **({'orientation': 'portrait'} if portrait else {})})}",
                    {"Authorization": key})
    out = []
    for it in d.get("videos" if kind == "video" else "photos", []):
        if kind == "video":
            files = sorted([f for f in it["video_files"] if f.get("height")], key=lambda f: -f["height"] * (f["height"] <= 2160))
            best = files[0] if files else None
            url, w, h, thumb = (best or {}).get("link"), it["width"], it["height"], it.get("image")
        else:
            url, w, h, thumb = it["src"]["original"], it["width"], it["height"], it["src"]["medium"]
        out.append({"provider": "pexels", "id": str(it["id"]), "kind": kind, "url": url, "thumb": thumb, "w": w, "h": h,
                    "title": it.get("alt") or q, "author": (it.get("user") or {}).get("name") or it.get("photographer"),
                    "license": "Pexels License", "license_url": "https://www.pexels.com/license/",
                    "page": it.get("url"), "duration": it.get("duration")})
    return out


def pixabay(q: str, kind: str, portrait: bool, n: int) -> list[dict]:
    key = os.environ.get("PIXABAY_API_KEY")
    if not key or kind == "audio":
        return []
    base = "https://pixabay.com/api/videos/" if kind == "video" else "https://pixabay.com/api/"
    params = {"key": key, "q": q, "per_page": max(3, n), "safesearch": "true",
              **({"orientation": "vertical"} if portrait and kind == "photo" else {}),
              **({"image_type": "photo"} if kind == "photo" else {})}
    d = cached_json(f"{base}?{urllib.parse.urlencode(params)}")
    out = []
    for it in d.get("hits", []):
        if kind == "video":
            v = it["videos"].get("large") or it["videos"].get("medium") or {}
            url, w, h, thumb = v.get("url"), v.get("width"), v.get("height"), v.get("thumbnail")
        else:
            url, w, h, thumb = it.get("largeImageURL"), it.get("imageWidth"), it.get("imageHeight"), it.get("webformatURL")
        out.append({"provider": "pixabay", "id": str(it["id"]), "kind": kind, "url": url, "thumb": thumb, "w": w, "h": h,
                    "title": it.get("tags") or q, "author": it.get("user"), "license": "Pixabay Content License",
                    "license_url": "https://pixabay.com/service/license-summary/", "page": it.get("pageURL"),
                    "duration": it.get("duration")})
    return out


def openverse(q: str, kind: str, portrait: bool, n: int) -> list[dict]:
    if kind == "video":
        return []
    ep = "audio" if kind == "audio" else "images"
    params = {"q": q, "license": "cc0,pdm,by,by-sa", "page_size": n, "mature": "false",
              **({"aspect_ratio": "tall"} if portrait and kind == "photo" else {})}
    d = cached_json(f"https://api.openverse.org/v1/{ep}/?{urllib.parse.urlencode(params)}")
    out = []
    for it in d.get("results", []):
        lic = f"CC {it['license'].upper()} {it.get('license_version') or ''}".strip() if it["license"] not in ("cc0", "pdm") \
            else ("CC0" if it["license"] == "cc0" else "Public Domain Mark")
        out.append({"provider": "openverse", "id": it["id"], "kind": kind, "url": it["url"], "thumb": it.get("thumbnail"),
                    "w": it.get("width"), "h": it.get("height"), "title": it.get("title") or q,
                    "author": it.get("creator"), "license": lic, "license_url": it.get("license_url"),
                    "page": it.get("foreign_landing_url"), "source": it.get("source"),
                    "duration": (it.get("duration") or 0) / 1000 if kind == "audio" else None})
    return out


def commons(q: str, kind: str, portrait: bool, n: int) -> list[dict]:
    if kind == "audio":
        return []
    ft = "filetype:video" if kind == "video" else "filetype:bitmap"
    params = {"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} {ft}",
              "gsrnamespace": "6", "gsrlimit": str(n * 3), "prop": "imageinfo",
              "iiprop": "url|size|extmetadata|mime", "iiurlwidth": "1280"}
    d = cached_json("https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params))
    out = []
    for p in sorted(d.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0)):
        ii = (p.get("imageinfo") or [{}])[0]
        em = ii.get("extmetadata", {})
        lic = strip_html(em.get("LicenseShortName", {}).get("value", ""))
        if not OK_CC.match(lic.replace("Public domain", "pd")):
            continue
        w, h = ii.get("width", 0), ii.get("height", 0)
        if kind == "photo" and (max(w, h) < 1400 or min(w, h) < 900):
            continue
        if portrait and kind == "photo" and h < w * 0.9 and h < 3000:  # Goa lesson: vertical crops need ~3000 px
            continue
        url = ii.get("url")
        if kind == "photo" and max(w, h) > 3840 and ii.get("thumburl"):
            # big originals: the largest standard thumb width below the original (never the 1280 preview)
            tw = max(s_ for s_ in COMMONS_SIZES if s_ < w)
            url = re.sub(r"/\d+px-", f"/{tw}px-", ii["thumburl"], count=1)
        out.append({"provider": "commons", "id": str(p["pageid"]), "kind": kind, "url": url, "thumb": ii.get("thumburl"),
                    "w": w, "h": h, "title": p["title"].removeprefix("File:").rsplit(".", 1)[0],
                    "author": strip_html(em.get("Artist", {}).get("value", "")) or "unknown", "license": lic,
                    "license_url": em.get("LicenseUrl", {}).get("value"), "page": ii.get("descriptionurl"),
                    "mime": ii.get("mime")})
        if len(out) >= n:
            break
    return out


PROVIDERS = {"pexels": pexels, "pixabay": pixabay, "openverse": openverse, "commons": commons}


def search(q: str, kind: str = "photo", provider: str = "auto", portrait: bool = False, n: int = 12) -> list[dict]:
    names = list(PROVIDERS) if provider == "auto" else [provider]
    res = []
    for name in names:
        try:
            res += PROVIDERS[name](q, kind, portrait, n)
        except Exception as e:  # noqa: BLE001
            print(f"  {name}: {str(e)[:120]}", file=sys.stderr)
    (CACHE / "last_search.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return res


def get(ref: str) -> Path:
    """Download '<provider>:<id>' from the last search; writes the file + .license.json."""
    prov, _, rid = ref.partition(":")
    last = json.loads((CACHE / "last_search.json").read_text(encoding="utf-8"))
    it = next((r for r in last if r["provider"] == prov and r["id"] == rid), None)
    if not it:
        raise SystemExit(f"{ref} not in the last search results")
    d = LIB / prov
    d.mkdir(parents=True, exist_ok=True)
    ext = Path(urllib.parse.urlparse(it["url"]).path).suffix.lower() or (".mp4" if it["kind"] == "video" else ".jpg")
    dest = d / f"{re.sub(r'[^A-Za-z0-9_-]', '', rid)[:40]}{ext}"
    if prov == "commons":  # pacing between downloads
        wait = 4.0 - (time.time() - _last_commons[0])
        if wait > 0:
            time.sleep(wait)
        _last_commons[0] = time.time()
    dest.write_bytes(http(it["url"]))
    if it["kind"] == "photo":
        from PIL import Image, ImageOps
        with Image.open(dest) as im:
            up = ImageOps.exif_transpose(im)
            if up is not im:
                up.save(dest, quality=95)
    meta = {**{k: it.get(k) for k in ("provider", "id", "kind", "title", "author", "license", "license_url", "page",
                                        "url", "w", "h", "duration")}, "file": dest.name,
            "downloaded": time.strftime("%Y-%m-%d")}
    dest.with_suffix(".license.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    return dest


def sheet(res: list[dict], query: str) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    import io
    tw, cols = 300, 4
    tiles = []
    for r in res[:16]:
        try:
            im = Image.open(io.BytesIO(http(r["thumb"]))).convert("RGB") if r.get("thumb") else Image.new("RGB", (tw, tw))
        except Exception:  # noqa: BLE001
            im = Image.new("RGB", (tw, tw), (40, 40, 40))
        im.thumbnail((tw, tw))
        tiles.append(im)
    rows = (len(tiles) + cols - 1) // cols or 1
    out = Image.new("RGB", (cols * tw, 30 + rows * (tw + 34)), (16, 16, 18))
    dr = ImageDraw.Draw(out)
    font = ImageFont.truetype(str(cfg.path("fonts") / "inter" / "Inter[opsz,wght].ttf"), 13)
    dr.text((8, 7), f"stock: {query}", fill=(255, 184, 48), font=font)
    for i, (r, im) in enumerate(zip(res, tiles)):
        x, y = (i % cols) * tw, 30 + (i // cols) * (tw + 34)
        out.paste(im, (x + (tw - im.width) // 2, y + (tw - im.height) // 2))
        dr.text((x + 4, y + tw + 2), f"{r['provider']}:{r['id']}"[:40], fill=(240, 236, 228), font=font)
        dr.text((x + 4, y + tw + 17), f"{r.get('w')}x{r.get('h')} {r['license']}"[:42], fill=(170, 170, 170), font=font)
    p = cfg.ROOT / "_previews" / "stock.jpg"
    p.parent.mkdir(exist_ok=True)
    out.save(p, quality=85)
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--kind", default="photo", choices=["photo", "video", "audio"])
    s.add_argument("--provider", default="auto", choices=["auto", *PROVIDERS])
    s.add_argument("--portrait", action="store_true")
    s.add_argument("--n", type=int, default=12)
    s.add_argument("--sheet", action="store_true")
    g = sub.add_parser("get")
    g.add_argument("refs", nargs="+")
    a = ap.parse_args()
    if a.cmd == "search":
        missing = [k for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY") if not os.environ.get(k)]
        if missing and a.provider in ("auto", "pexels", "pixabay"):
            print(f"note: {', '.join(missing)} not set; those providers are skipped (⛔ USER: add free keys)")
        res = search(a.query, a.kind, a.provider, a.portrait, a.n)
        for r in res:
            print(f"{r['provider']}:{r['id']:<14} {str(r.get('w')) + 'x' + str(r.get('h')):<11} {r['license']:<22} "
                  f"{(r.get('author') or '')[:22]:<22} {r['title'][:50]}")
        print(f"{len(res)} results")
        if a.sheet and res:
            print(f"sheet: {sheet(res, a.query)}")
    else:
        for ref in a.refs:
            print(f"saved {get(ref)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

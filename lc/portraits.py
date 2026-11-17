"""Driver portraits from formulad.com (Joshua may use them with credit to @formulad).

Run on GitHub Actions (workflow 'handles'): python -m lc.portraits
Saves docs/media/portraits/<slug>.jpg and data/portraits.json {name key: {src, credit, name, page}}.
"""
from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

import requests

from .handles import _key

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "docs" / "media" / "portraits"
INDEX = ROOT / "data" / "portraits.json"
BASE = "https://www.formulad.com"
UA = {"User-Agent": "Mozilla/5.0 (sidewayswire portraits)"}


def index() -> dict:
    return json.loads(INDEX.read_text()) if INDEX.exists() else {}


def candidates(html: str, slug: str) -> list[str]:
    urls = []
    for m in re.finditer(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html):
        urls.append(m.group(1))
    for m in re.finditer(r'<img[^>]+(?:src|data-src)="([^"]+)"[^>]*>', html):
        u, tag = m.group(1), m.group(0).lower()
        if any(w in (u.lower() + tag) for w in (slug.split("-")[-1], "driver", "headshot", "portrait", "profile")):
            urls.append(u)
    for m in re.finditer(r'srcset="([^"]+)"', html):
        best = m.group(1).split(",")[-1].strip().split(" ")[0]
        if slug.split("-")[-1] in best.lower() or "driver" in best.lower():
            urls.append(best)
    out = []
    for u in urls:
        u = u.replace("&amp;", "&")
        u = BASE + u if u.startswith("/") else u
        if u.startswith("http") and not re.search(r"logo|icon|sprite|\.svg", u, re.I) and u not in out:
            out.append(u)
    return out


def run() -> dict:
    from PIL import Image
    DIR.mkdir(parents=True, exist_ok=True)
    ix = index()
    page = requests.get(f"{BASE}/drivers", headers=UA, timeout=30).text
    slugs = sorted(set(re.findall(r'/drivers/([a-z0-9-]+)', page)))
    report = {"profiles": len(slugs), "saved": 0, "failed": []}
    for slug in slugs:
        try:
            html = requests.get(f"{BASE}/drivers/{slug}", headers=UA, timeout=30).text
            m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            name = re.sub(r"<[^>]+>|\s+", " ", m.group(1)).strip() if m else slug.replace("-", " ").title()
            best = None
            for u in candidates(html, slug)[:6]:
                r = requests.get(u, headers=UA, timeout=30)
                if not r.ok:
                    continue
                im = Image.open(io.BytesIO(r.content)).convert("RGB")
                w, h = im.size
                if min(w, h) < 300:
                    continue
                score = (h / w >= 0.9) * 2 + min(w * h, 2e6) / 1e6     # prefer portrait-shaped, then bigger
                if best is None or score > best[0]:
                    best = (score, im, u)
            if not best:
                report["failed"].append(f"{slug}: geen portret gevonden"); continue
            _, im, u = best
            im.thumbnail((900, 1200))
            dest = DIR / f"{slug}.jpg"
            im.save(dest, quality=88)
            ix[_key(name)] = {"src": str(dest.relative_to(ROOT)), "credit": "@formulad", "name": name,
                              "page": f"{BASE}/drivers/{slug}", "url": u}
            report["saved"] += 1
            time.sleep(0.4)
        except Exception as e:
            report["failed"].append(f"{slug}: {str(e)[:80]}")
    INDEX.write_text(json.dumps(ix, indent=1, ensure_ascii=False))
    return report


def pick(people: list[str]) -> dict | None:
    ix = index()
    for p in people:
        e = ix.get(_key(p))
        if e and (ROOT / e["src"]).exists():
            return e
    return None


if __name__ == "__main__":
    r = run()
    print({k: v for k, v in r.items() if k != "failed"}, "failed:", len(r["failed"]))
    print("\n".join(r["failed"][:20]))

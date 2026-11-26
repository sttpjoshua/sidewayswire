"""Find Instagram handles for the names that still hold posts back (TAGS on the dashboard).

Runs on GitHub (workflow 'handles', input zoek_tags), because it needs the Meta token. For every open
name it collects candidate handles (from the driver page on dm.gp or formulad.com when there is one, and
the usual spellings of the name), then asks Instagram (Business Discovery) whether the account exists and
what its name, bio and followers are. Only accounts whose name or bio fits the person are kept.

Nothing is tagged from this on its own: good matches go into data/sources.csv with Status
"Te controleren" and the evidence in Notitie, so the dashboard shows KLOPT @handle with a link to the
profile, and Joshua confirms with one click.

    python -m lc.verify_handles            (writes data/handle_suggestions.json and updates sources.csv)
"""
from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "sources.csv"
OUT = ROOT / "data" / "handle_suggestions.json"
UA = {"User-Agent": "Mozilla/5.0 (sidewayswire source list)"}
NOT_PEOPLE = {"unknown driver", "lucas", "fia", "red bull car park drift"}
DRIFT = re.compile(r"drift|formula ?d|drift ?masters|d1|motorsport|racing|driver|pro ?am|#\d+", re.I)


def _plain(s: str) -> str:
    s = s.translate(str.maketrans({"ø": "o", "ł": "l", "æ": "ae", "ß": "ss"}))
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def candidates(name: str) -> list[str]:
    parts = [re.sub(r"[^a-z0-9]", "", p) for p in _plain(name).split()]
    parts = [p for p in parts if p]
    if len(parts) < 2:
        return []
    f, l = parts[0], parts[-1]
    base = [f + l, f + "_" + l, f + "." + l, l + f, f + l + "drift", f + "_" + l + "_", f[0] + l,
            l + "drift", f + l + "_", "_" + f + l, f + "." + l + "_"]
    return list(dict.fromkeys(base))


_BASE: dict[str, set] = {}


def _base(host: str, url: str) -> set:
    """Handles that are on every page of a site (header, footer, sponsors): never a driver's own."""
    if host not in _BASE:
        try:
            t = requests.get(url, headers=UA, timeout=20).text
            _BASE[host] = {h.lower().rstrip(".") for h in re.findall(r"instagram\.com/([A-Za-z0-9_.]+)", t)}
        except Exception:
            _BASE[host] = set()
    return _BASE[host]


def page_handles(name: str) -> list[str]:
    """Instagram links on the official driver page (Drift Masters, Formula DRIFT). Only when the page
    really is that driver's page: no redirect, his name on it, and not a link that every page has
    (26 nov: dm.gp sent unknown drivers to a general page with @adam_lz on it)."""
    slug = re.sub(r"[^a-z0-9]+", "-", _plain(name)).strip("-")
    last = _plain(name).split()[-1]
    out = []
    for host, url, dummy in (("dm.gp", f"https://dm.gp/drivers/{slug}/", "https://dm.gp/drivers/zz-not-a-driver/"),
                             ("formulad", f"https://www.formulad.com/drivers/{slug}", "https://www.formulad.com/drivers/zz-not-a-driver")):
        try:
            r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        except Exception:
            continue
        if r.status_code != 200 or slug not in r.url or last not in _plain(r.text):
            continue
        base = _base(host, dummy)
        hs = [h.lower().rstrip(".") for h in re.findall(r"instagram\.com/([A-Za-z0-9_.]+)", r.text)]
        hs = [h for h in hs if h not in base and h not in ("p", "reel", "explore")]
        out += hs[:1]
    return list(dict.fromkeys(out))


SERIES_ACCOUNTS = ["driftmasters.gp", "formulad", "redbullmotorsports", "d1grandprix_official", "drifted_com",
                   "driftgames.life", "irishdriftchampionship"]


def captions(ig, accounts=SERIES_ACCOUNTS, pages: int = 4) -> list[str]:
    """Recent captions of the series' own accounts: they tag the drivers ("Lauri Heinonen @...")."""
    out = []
    for acc in accounts:
        after = ""
        for _ in range(pages):
            try:
                cur = f".after({after})" if after else ""
                d = ig._get(ig.user_id, fields=f"business_discovery.username({acc}){{media.limit(50){cur}{{caption}}}}")
            except Exception:
                break
            media = (d.get("business_discovery") or {}).get("media") or {}
            out += [m.get("caption") or "" for m in media.get("data", [])]
            after = ((media.get("paging") or {}).get("cursors") or {}).get("after")
            if not after:
                break
            time.sleep(0.5)
    return out


def from_captions(name: str, caps: list[str]) -> list[str]:
    """@handles written right after the person's name (or surname) in series captions, most frequent first."""
    from collections import Counter
    keys = [_plain(name), _plain(name).split()[-1]]
    found = Counter()
    for c in caps:
        pc = _plain(c)
        for k in keys:
            if len(k) < 4:
                continue
            for m in re.finditer(re.escape(k), pc):
                seg = c[m.start(): m.start() + len(k) + 40]
                h = re.findall(r"@([A-Za-z0-9_.]+)", seg)
                if h:
                    found[h[0].lower().rstrip(".")] += 2 if k == keys[0] else 1
    return [h for h, _ in found.most_common(3)]


def check(ig, username: str) -> dict | None:
    try:
        d = ig._get(ig.user_id, fields=f"business_discovery.username({username}){{username,name,biography,followers_count,media_count}}")
        return d.get("business_discovery")
    except Exception as e:
        if any(c in str(e) for c in ("(#4)", "(#17)", "(#32)", "(#613)", "rate")):
            raise
        return None


def fits(name: str, acc: dict, official: bool) -> tuple[bool, str]:
    who = _plain(acc.get("name") or "")
    bio = acc.get("biography") or ""
    sim = SequenceMatcher(None, re.sub(r"[^a-z]", "", _plain(name)), re.sub(r"[^a-z]", "", who)).ratio()
    last = re.sub(r"[^a-z]", "", _plain(name).split()[-1])
    has_last = last and last in re.sub(r"[^a-z]", "", who + _plain(acc.get("username", "")))
    drift = bool(DRIFT.search(bio + " " + (acc.get("name") or "")))
    if official and (sim >= 0.5 or has_last or drift):
        return True, "staat op de officiële rijderspagina"
    if (sim >= 0.8 or has_last) and drift:
        return True, f"naam past ({acc.get('name')}), bio over drift"
    if sim >= 0.9 and (acc.get("followers_count") or 0) >= 2000:
        return True, f"naam past precies ({acc.get('name')}), {acc.get('followers_count')} volgers"
    return False, ""


def run() -> dict:
    from .handles import open_names, registry, lookup
    from . import queue as q
    from .instagram import Instagram
    ig = Instagram()
    reg = registry()
    names = [n["name"] for n in open_names(q.load()) if n["name"].lower() not in NOT_PEOPLE]
    result = {}
    caps = captions(ig)
    result["_captions"] = len(caps)
    for name in names:
        r = lookup(reg, name)
        if r and r.get("handle"):
            continue                              # handle known, only Joshua's check is missing
        official = page_handles(name)
        tagged = [h for h in from_captions(name, caps) if h not in official]
        found = []
        for h in official + tagged + [c for c in candidates(name) if c not in official + tagged]:
            try:
                acc = check(ig, h)
            except Exception as e:
                result["_stopped"] = f"Instagram-limiet bij {name}: {str(e)[:120]}"
                break
            time.sleep(0.5)
            if not acc:
                continue
            ok, why = fits(name, acc, h in official)
            if not ok and h in tagged:
                ok, why = fits(name, acc, True)
                why = "getagd bij zijn naam door de serie zelf" if ok else ""
            if ok:
                found.append({"handle": "@" + acc["username"].lower(), "name": acc.get("name"), "why": why,
                              "followers": acc.get("followers_count"), "bio": (acc.get("biography") or "")[:140]})
                break
        result[name] = found
        if "_stopped" in result:
            break
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n")
    # into the sources sheet, for one-click confirmation on the dashboard
    rows = list(csv.DictReader(CSV.open(encoding="utf-8")))
    fields = list(rows[0].keys())
    by = {r["Naam"].lower(): r for r in rows}
    added = 0
    for name, fs in result.items():
        if name.startswith("_") or not isinstance(fs, list) or not fs:
            continue
        f = fs[0]
        r = lookup(reg, name)
        row = by.get((r or {}).get("name", name).lower())
        note = f"gevonden door Claude {time.strftime('%Y-%m-%d')}: {f['why']}"
        if row:
            if not row.get("Instagram"):
                row.update(Instagram=f["handle"], Status="Te controleren", Notitie=(row.get("Notitie") or "") + " | " + note)
                added += 1
        else:
            rows.append({k: "" for k in fields} | {"Naam": name, "Type": "Coureur", "Prioriteit": "2",
                                                  "Instagram": f["handle"], "Status": "Te controleren", "Notitie": note})
            added += 1
    with CSV.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return {"names": len(names), "captions": result.get("_captions"), "found": sum(1 for k, v in result.items() if not k.startswith("_") and v),
            "added": added, "stopped": result.get("_stopped")}


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))

"""Instagram handles for captions.

Only handles marked 'Gecontroleerd' in data/sources.csv are used. The editor never types
handles: a moment lists the people in it ("people": ["Tommy Lemaire"]) and this module
builds the tag line from the registry. Names without a checked handle come back as
'missing', so the post goes to Joshua with 'handles nakijken'.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "sources.csv"
MANUAL = ROOT / "data" / "handles_manual.json"   # handles Joshua typed in the dashboard: checked by him
SHOWS = ROOT / "data" / "podcasts" / "shows.json"
OWN = "@sidewayswire"


_TRANSLIT = str.maketrans({"ø": "o", "Ø": "O", "ł": "l", "Ł": "L", "æ": "ae", "Æ": "AE", "ß": "ss", "đ": "d",
                           "Đ": "D", "œ": "oe", "þ": "th", "ı": "i"})


def _key(name: str) -> str:
    """Aasbø, Aasbo and AASBO are the same key (also letters NFKD does not split, like ø and ł)."""
    s = unicodedata.normalize("NFKD", str(name).translate(_TRANSLIT)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def registry() -> dict:
    """Everyone we may tag, by key. Every alias (other spellings, speech-recognition mistakes) is a key too,
    pointing to the same person. Per person: name (official spelling), handle, ok (handle checked),
    none (checked: has no Instagram, so nothing is missing), type, prio.

    Sources: data/sources.csv (column Aliassen, separated by |; Status 'Geen Instagram') and
    data/handles_manual.json from the dashboard: {"Name": "@handle" | "-" (no Instagram) | "=Official Name" (alias)}."""
    out, alias = {}, {}
    for r in csv.DictReader(CSV.open(encoding="utf-8")):
        ig = (r.get("Instagram") or "").strip()
        e = {"name": r["Naam"], "handle": ig.lower() if ig else "",
             "ok": r.get("Status") == "Gecontroleerd" and ig.startswith("@"),
             "none": r.get("Status") == "Geen Instagram",
             "type": r.get("Type", ""), "prio": int(r.get("Prioriteit") or 3), "series": r.get("Serie", "")}
        out[_key(r["Naam"])] = e
        for a in (r.get("Aliassen") or "").split("|"):
            if a.strip():
                alias[_key(a)] = _key(r["Naam"])
    if MANUAL.exists():
        for name, v in json.loads(MANUAL.read_text()).items():
            v = str(v).strip()
            if v.startswith("="):
                alias[_key(name)] = _key(v[1:])
                continue
            base = out.get(_key(name), {"type": "", "prio": 3, "series": ""})
            if v == "-":
                out[_key(name)] = {**base, "name": base.get("name") or name, "handle": "", "ok": False, "none": True}
                continue
            ig = "@" + v.lstrip("@").lower()
            if len(ig) > 1:
                out[_key(name)] = {**base, "name": base.get("name") or name, "handle": ig, "ok": True, "none": False}
    for a, k in alias.items():
        if k in out and a not in out:
            out[a] = out[k]
    return out


def lookup(reg: dict, name: str) -> dict | None:
    """The person for a name: exact key or alias first; else one clear near match among the people we know
    (Brandon/Branden Sorensen, Jonathan/Jhonnattan Castro). A near match only counts when it is the only
    good candidate and the surname matches closely, so two Sorensens never get mixed up."""
    k = _key(name)
    if not k:
        return None
    if k in reg:
        return reg[k]
    from difflib import SequenceMatcher
    parts = [_key(x) for x in str(name).split() if _key(x)]
    if len(parts) < 2:
        return None
    sur = parts[-1]
    scored = []
    for rk, r in reg.items():
        rp = [_key(x) for x in r["name"].split() if _key(x)]
        if len(rp) < 2 or r.get("type") not in ("Coureur", "Presentator", ""):
            continue
        s_sur = SequenceMatcher(None, sur, rp[-1]).ratio()
        if s_sur < 0.85:
            continue
        scored.append((SequenceMatcher(None, k, _key(r["name"])).ratio(), s_sur, r["name"], r))
    scored.sort(key=lambda x: -x[0])
    best = [x for x in scored if x[0] >= 0.84]
    names = {x[2] for x in best}
    if len(names) == 1 and (len(scored) == len(best) or scored[len(best)][0] < 0.75):
        return best[0][3]
    return None


def shows() -> dict:
    return json.loads(SHOWS.read_text()) if SHOWS.exists() else {}


def people(m: dict) -> list[str]:
    if m.get("people"):
        return [p for p in m["people"] if p]
    g = m.get("guest") or ""
    return [p.strip().title() for p in re.split(r"\s*(?:&|,|\band\b|\bvs\.?\b)\s*", g, flags=re.I) if p.strip()]


def mentioned(m: dict, reg: dict) -> list[str]:
    """People named in full in the moment (quote, topic, caption), e.g. 'James Deane'."""
    text = _key(" ".join(str(m.get(k) or "") for k in ("quote", "topic", "caption")))
    return [r["name"] for k, r in reg.items() if len(r["name"].split()) >= 2 and len(k) >= 8 and k in text]


def compose(ep: dict, m: dict) -> tuple[str, list[str], list[str]]:
    """Returns (caption, handles, missing names)."""
    reg = registry()
    show = shows().get(ep.get("podcast", ""), {})
    names = people(m) + mentioned(m, reg) + list(show.get("hosts", [])) + list(show.get("tags", []))
    handles, missing = [], []
    for n in names:
        r = lookup(reg, n)
        if r and r["ok"]:
            if r["handle"] not in handles:
                handles.append(r["handle"])
        elif r and r.get("none"):
            continue                               # checked: this person has no Instagram
        elif n not in missing and (not r or r["name"] not in missing):
            missing.append(r["name"] if r else n)
    if ep.get("kind") in ("stream", "vlog") and ep.get("credit") and ep["credit"].lower() not in handles:
        handles.append(ep["credit"].lower())
    text = m.get("caption") or m.get("topic", "").capitalize()
    tags = re.findall(r"#\w+", text)
    lines = [l for l in text.splitlines() if not re.match(r"\s*(full episode|footage|credit)\b", l, re.I)]
    body = re.sub(r"(?<!\w)@[\w.]+", "", "\n".join(lines))
    body = re.sub(r"#\w+", "", body)
    body = re.sub(r"[ \t]+", " ", re.sub(r" +([,.!?])", r"\1", body)).strip()
    if "#sidewayswire" not in [t.lower() for t in tags]:
        tags.append("#sidewayswire")
    src = (f"🎥 Full video: {ep.get('creator') or ep.get('podcast')} on YouTube" if ep.get("kind") == "vlog"
           else f"🎥 Footage: {ep.get('event') or ep.get('title', '')}" if ep.get("kind") == "stream"
           else f"🎙 Full episode: {show.get('label') or ep.get('podcast', '')}")
    caption = f"{body}\n\n{src}\n{' '.join(handles)}\n\n{' '.join(dict.fromkeys(tags))}".replace("\n\n\n", "\n\n")
    return caption, handles, missing


def suggestions(reg: dict, name: str, n: int = 3) -> list[str]:
    """Closest people we know, for the dashboard ("is this Branden Sorensen?")."""
    from difflib import SequenceMatcher
    k = _key(name)
    seen, out = set(), []
    for r in sorted(reg.values(), key=lambda r: -SequenceMatcher(None, k, _key(r["name"])).ratio()):
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        if SequenceMatcher(None, k, _key(r["name"])).ratio() >= 0.6:
            out.append(r["name"])
        if len(out) >= n:
            break
    return out


def open_names(posts: list[dict]) -> list[dict]:
    """Every name that still holds posts back, with how many posts wait for it (dashboard, TAGS).
    One answer per name fixes all those posts at once."""
    reg = registry()
    out: dict[str, dict] = {}
    for p in posts:
        if p.get("status") in ("posted", "skipped"):
            continue
        names = list(p.get("missing_handles") or [])
        if p.get("status") == "check" and p.get("check_reason") == "namen nakijken":
            names += [x for x in (p.get("people") or []) if not lookup(reg, x)]
        for nm in dict.fromkeys(names):
            r = lookup(reg, nm)
            e = out.setdefault(nm, {"name": nm, "posts": 0, "ids": [],
                                    "handle": (r or {}).get("handle", ""), "known": bool(r),
                                    "series": (r or {}).get("series", ""),
                                    "suggest": [] if r else suggestions(reg, nm)})
            e["posts"] += 1
            if len(e["ids"]) < 6:
                e["ids"].append(p["id"])
    return sorted(out.values(), key=lambda e: -e["posts"])

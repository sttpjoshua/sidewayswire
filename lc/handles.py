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


def _key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def registry() -> dict:
    out = {}
    for r in csv.DictReader(CSV.open(encoding="utf-8")):
        ig = (r.get("Instagram") or "").strip()
        out[_key(r["Naam"])] = {"name": r["Naam"], "handle": ig.lower() if ig else "",
                                "ok": r.get("Status") == "Gecontroleerd" and ig.startswith("@"),
                                "type": r.get("Type", ""), "prio": int(r.get("Prioriteit") or 3)}
    if MANUAL.exists():
        for name, ig in json.loads(MANUAL.read_text()).items():
            ig = "@" + ig.strip().lstrip("@").lower()
            if len(ig) > 1:
                out[_key(name)] = {**out.get(_key(name), {"type": "", "prio": 3}), "name": name, "handle": ig, "ok": True}
    return out


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
        r = reg.get(_key(n))
        if r and r["ok"]:
            if r["handle"] not in handles:
                handles.append(r["handle"])
        elif n not in missing:
            missing.append(n)
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

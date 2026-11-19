"""Kop-posts: one big headline on a coloured tape, the driver in front of a still (templates/hook.html).

Learned from DriftReady (Joshua, 19 nov 2026): on Facebook the community is built with image posts that
carry one headline, not with video. Six kinds, each with its own job:

    breaking  departure, transfer, new team        -> shares     (goes out within a few hours)
    winner    after a win, with a one-line story    -> reach
    question  open question on real news           -> comments  ("Which team...?")
    whatif    a fan favourite, "what if"           -> likes and comments
    debate    a sore point in the sport            -> everything (light stance, never bashing)
    look      new car or livery (own still only)    -> easy likes

The local editor (tools/mac/local_editor.py) makes breaking, winner, look and question posts from news.
This module keeps a few question posts without factual claims in stock (data/hooks/questions.json):
more in the off-season, when fans want to guess. Runs in every run before the build:

    python -m lc.hooks
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import queue as q

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "data" / "hooks" / "questions.json"
USED = ROOT / "data" / "hooks" / "used.json"

TYPES = ("breaking", "winner", "question", "whatif", "debate", "look")
LABELS = {"breaking": "BREAKING", "winner": "WINNER", "question": "YOUR CALL", "whatif": "WHAT IF?",
          "debate": "HOT TAKE", "look": "NEW LOOK"}
# Tape colours: a fixed look with a changing colour, like DriftReady. White text with a black edge reads on all.
PALETTE = ["#C6FF00", "#FF2E88", "#1E6BFF", "#E10600", "#00B3A4", "#FF7A00", "#7B2CFF", "#111111"]
SERIES = {"Formula DRIFT": "FORMULA DRIFT", "FD": "FORMULA DRIFT", "Drift Masters": "DRIFT MASTERS",
          "DM": "DRIFT MASTERS", "D1GP": "D1 GRAND PRIX", "D1": "D1 GRAND PRIX"}
OFF_SEASON = {11, 12, 1, 2, 3}           # months without FD or DM rounds: fans speculate, so more questions
STOCK = {"off": 4, "on": 2}              # evergreen question posts kept waiting at any time
REUSE_DAYS = 120


def band(post_id: str) -> str:
    return PALETTE[sum(map(ord, post_id)) % len(PALETTE)]


def series_label(s: str | None) -> str:
    s = (s or "").strip()
    return SERIES.get(s, s.upper())[:24]


def make(kind: str, headline: list[str], caption: str, people: list[str] | None = None, series: str = "",
         post_id: str | None = None, tags: list[str] | None = None, **extra) -> dict:
    """A draft kop-post. The build adds the still, the portrait and the colour."""
    assert kind in TYPES, kind
    now = datetime.now(timezone.utc)
    pid = post_id or f"{now:%Y-%m-%d}-{kind}-{hashlib.md5(' '.join(headline).encode()).hexdigest()[:6]}"
    cap = caption.strip()
    if tags:
        cap += "\n\n" + " ".join(tags[:3])
    return {"id": pid, "kind": "breaking" if kind == "breaking" else "hook", "hook": {"type": kind},
            "title": " ".join(headline), "people": people or [],
            "slides": [{"template": "hook.html", "data": {
                "headline": [h.upper() for h in headline][:3], "label": LABELS[kind],
                "series": series_label(series)}}],
            "caption": cap, "platforms": ["instagram", "facebook"], "status": "draft",
            "created": now.isoformat(), **extra}


def learned() -> dict:
    """What worked for us (docs/stats.json, by format), once a format has enough measured posts.
    Returns {"rank": [question types, best first], "extra": 0 or 1 extra question post in stock}."""
    f = ROOT / "docs" / "stats.json"
    try:
        bf = json.loads(f.read_text()).get("by_format") or {}
    except Exception:
        bf = {}
    qs = {t: v["engagement"] for t, v in bf.items() if t in ("question", "whatif", "debate") and v.get("enough")}
    rank = sorted(qs, key=lambda t: -qs[t])
    rest = [v["engagement"] for t, v in bf.items() if t not in qs and v.get("enough")]
    extra = int(bool(qs) and bool(rest) and max(qs.values()) > sum(rest) / len(rest))
    return {"rank": rank, "extra": extra}


def _used() -> dict:
    return json.loads(USED.read_text()) if USED.exists() else {}


def feed(now: datetime | None = None, folder: Path = q.QUEUE) -> list[str]:
    """Tops up the stock of evergreen question posts. Returns the ids it added."""
    now = now or datetime.now(timezone.utc)
    learn = learned()
    want = STOCK["off" if now.astimezone(q.TZ).month in OFF_SEASON else "on"] + learn["extra"]
    waiting = [p for p in q.load(folder=folder)
               if p.get("evergreen") and p.get("status") in ("draft", "ready", "check", "approved")]
    if len(waiting) >= want:
        return []
    bank = json.loads(QUESTIONS.read_text())["questions"]
    used = _used()
    fresh = [x for x in bank if x["id"] not in used]
    if not fresh:          # all used once: start again with the ones used longest ago
        cut = (now - timedelta(days=REUSE_DAYS)).isoformat()
        fresh = sorted((x for x in bank if used.get(x["id"], "") < cut), key=lambda x: used.get(x["id"], ""))
    if learn["rank"]:          # the question type that got the most reactions goes first
        fresh.sort(key=lambda x: learn["rank"].index(x["type"]) if x["type"] in learn["rank"] else 9)
    busy = {p.get("evergreen") for p in waiting}
    added = []
    for x in fresh:
        if len(waiting) + len(added) >= want:
            break
        if x["id"] in busy:
            continue
        p = make(x["type"], x["headline"], x["caption"], x.get("people"), x.get("series", ""),
                 post_id=f"q-{now:%Y%m%d}-{x['id']}", tags=x.get("tags"), evergreen=x["id"], by="hooks")
        q.save(p, folder)
        used[x["id"]] = now.isoformat()
        added.append(p["id"])
    if added:
        USED.parent.mkdir(parents=True, exist_ok=True)
        USED.write_text(json.dumps(used, indent=1) + "\n")
    return added


def add_media(drafts: list[dict]) -> None:
    """Colour, livestream still and driver portrait (cut-out when we have one) for kop-posts."""
    from . import portraits, stills
    used = set()
    for p in drafts:
        sl = (p.get("slides") or [{}])[0]
        if sl.get("template") != "hook.html":
            continue
        d = sl.setdefault("data", {})
        d.setdefault("band", band(p["id"]))
        credits = []
        people = p.get("people") or []
        want = CREDIT_OF.get(d.get("series") or "")
        foreign = bool(d.get("series")) and not want      # e.g. D1GP: an FD still would show the wrong series
        if not d.get("photo") and not p.get("no_still") and not foreign:
            e = stills.pick(people, used)
            if e and want and e["credit"] != want:
                e = None
            if e:
                used.add(e["src"])
                d["photo"], d["photo_credit"] = "../" + e["src"], e["credit"]
                credits.append(e["credit"])
        if not (d.get("cutout") or d.get("portrait")) and not p.get("no_portrait"):
            e = portraits.pick(people)
            if e:
                if e.get("cutout") and (ROOT / e["cutout"]).exists():
                    d["cutout"] = "../" + e["cutout"]
                else:
                    d["portrait"] = {"src": "../" + e["src"], "name": e["name"]}
                d["portrait_credit"] = e["credit"]
                credits.append(e["credit"])
        if not d.get("photo") and not p.get("no_still") and not people:
            e = _any_still(p["id"], d.get("series") or "", used)   # a question without a driver: any battle still
            if e:
                used.add(e["src"])
                d["photo"], d["photo_credit"] = "../" + e["src"], e["credit"]
                credits.append(e["credit"])
        if not d.get("photo"):
            d.setdefault("backdrop", {"FORMULA DRIFT": "FD", "DRIFT MASTERS": "DM", "D1 GRAND PRIX": "D1"}.get(d.get("series") or "", "DRIFT"))
        credits = list(dict.fromkeys(c for c in credits if c))
        cap = p.get("caption") or ""
        line = "Photo: " + " ".join(credits) if credits else ""
        if line and line not in cap:
            body, sep, tags = cap.rpartition("\n\n")
            p["caption"] = (f"{body}\n\n{line}\n\n{tags}" if sep and tags.strip().startswith("#")
                            else f"{cap}\n\n{line}").strip()


CREDIT_OF = {"FORMULA DRIFT": "@formulad", "DRIFT MASTERS": "@driftmasters"}


def _any_still(post_id: str, series: str, used: set) -> dict | None:
    """A livestream still that fits the series (any series when the question names none)."""
    from . import stills
    pool = {e["src"]: e for v in stills.index().values() for e in v}
    want = CREDIT_OF.get(series)
    if series and not want:
        return None                       # e.g. D1GP: we have no footage of our own
    pool = [e for src, e in sorted(pool.items()) if (not want or e["credit"] == want)
            and src not in used and (ROOT / src).exists()]
    return pool[sum(map(ord, post_id)) % len(pool)] if pool else None


if __name__ == "__main__":
    print(json.dumps({"added": feed()}, indent=1))

"""Hoe dringend is een beeldpost (nieuws, kop-post)? Een getal van 0 tot 100.

Joshua (27 nov): echt nieuws moet zo snel mogelijk online. Daarom telt het oordeel van de nieuwsscout
ook na het schrijven nog mee, en gaat alles vanaf URGENT_AT direct de deur uit in plaats van in het
ochtendslot. De rest van het nieuws wordt op urgentie gepland, niet meer op leeftijd.

    soort post   breaking 60, winner 55, uitslag/kampioen/kwalificatie 60, gerucht 45, nieuws 30,
                 nieuwe auto (look) 30, vraag/what-if/debat 5 (evergreen)
    + scout      de helft van de scoutscore van het verhaal (hoogstens 40)
    + tip        +20 als Joshua het zelf tipte
    - leeftijd   1 punt per 3 uur sinds het verhaal binnenkwam
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URGENT_AT = 60
BASE = {"breaking": 60, "winner": 55, "rumor": 45, "look": 30, "news": 30,
        "question": 5, "whatif": 5, "debate": 5,
        "result": 60, "champion": 60, "quali": 55, "livestream": 60}


def scout_scores() -> dict:
    """Story title -> scout score, from the inbox."""
    f = ROOT / "data" / "inbox.json"
    try:
        return {s.get("title", ""): (s.get("scout") or {}).get("score") for s in json.loads(f.read_text()).get("stories", [])}
    except Exception:
        return {}


def kind_of(p: dict) -> str:
    h = (p.get("hook") or {}).get("type")
    return h or p.get("kind") or "news"


def urgency(p: dict, scores: dict | None = None, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    if p.get("evergreen"):
        return 5
    s = BASE.get(kind_of(p), 30)
    sc = p.get("scout_score")
    if sc is None and scores is not None:
        sc = scores.get(p.get("story") or "")
    s += min(40, max(0, int(sc or 20) // 2))
    if p.get("tip"):
        s += 20
    born = p.get("created") or p.get("built")
    try:
        b = datetime.fromisoformat(born)
        b = b if b.tzinfo else b.replace(tzinfo=timezone.utc)
        s -= int(max(0, (now - b).total_seconds()) / 3600 / 3)
    except Exception:
        pass
    return max(0, min(100, s))


def is_urgent(p: dict) -> bool:
    return (p.get("urgency") or 0) >= URGENT_AT

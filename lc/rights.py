"""Van wie is een post? eigen / toestemming / geleend (Joshua, 27 nov: basis om geld te verdienen).

- eigen: beeldposts die het systeem zelf maakt (kop-posts, nieuws, vragen, standen).
- toestemming: clips uit kanalen of streams met "permission" in data/streams/streams.json
  (vlogs van rijders, de Red Bull TV-replays). "commercial" in data/permissions.json zegt of de toestemming
  ook geld verdienen dekt; zolang dat niet bevestigd is, telt het niet mee voor monetisatie.
- geleend: al het andere (officiele livestreams en podcasts zonder afspraak): goed voor bereik, niet voor geld.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REEL_KINDS = {"podcast_clip", "stream_clip", "vlog_clip", "battle_reel"}


def _load(path: str, default):
    try:
        return json.loads((ROOT / path).read_text())
    except Exception:
        return default


def permitted() -> dict:
    """credit handle or stream id -> {"who", "how", "commercial"}"""
    st, perm = _load("data/streams/streams.json", {}), _load("data/permissions.json", {}).get("who", {})
    out = {}
    for c in st.get("channels", []) + st.get("streams", []):
        if not c.get("permission"):
            continue
        key = c.get("id") if c in st.get("streams", []) else c.get("credit")
        who = c.get("series") or c.get("title") or key
        if c in st.get("streams", []):
            who = "Red Bull TV (Drift Masters)" if "redbull" in str(c.get("youtube", "")) else who
        p = perm.get(who, {})
        out[key] = {"who": who, "how": c["permission"], "commercial": bool(p.get("commercial")), "proof": p.get("proof", "")}
    return out


def rights_of(p: dict, perms: dict | None = None) -> dict:
    perms = perms if perms is not None else permitted()
    if p.get("kind") not in REEL_KINDS:
        return {"r": "eigen", "money": True}
    ep = p["id"].split("-")[1] if p["id"].startswith("pod-") else ""
    hit = perms.get(ep) or perms.get(p.get("credit") or "")
    if hit:
        return {"r": "toestemming", "who": hit["who"], "money": hit["commercial"]}
    return {"r": "geleend", "money": False}

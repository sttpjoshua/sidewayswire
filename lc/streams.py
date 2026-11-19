"""Livestreams (Formula DRIFT, Drift Masters) as a second kind of source next to podcasts.

data/streams/streams.json   the events we want clips from (written by Claude / the dashboard)
data/streams/mac/<id>.json  what the Mac helper found: the YouTube video, its length, transcript status
                            (only the Mac writes these, so nothing collides)
Transcripts go to data/podcasts/t/<id>.json like podcast transcripts, moments to data/podcasts/moments/,
so the studio, the editor and the clip maker treat a stream like an episode with kind "stream".
Footage is used with permission of the series, always credited with their @handle in the video.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "streams"


def registry() -> list[dict]:
    """Events from streams.json plus the replays the Mac found by itself (data/streams/mac/_found.json)."""
    f, g = DIR / "streams.json", DIR / "mac" / "_found.json"
    out = json.loads(f.read_text())["streams"] if f.exists() else []
    have = {s["id"] for s in out} | {s.get("youtube") for s in out}
    for s in (json.loads(g.read_text()).get("streams", []) if g.exists() else []):
        if s["id"] not in have and s.get("youtube") not in have:
            out.append(s)
    return out


def episodes() -> dict:
    out = {}
    for s in registry():
        mf = DIR / "mac" / f"{s['id']}.json"
        mac = json.loads(mf.read_text()) if mf.exists() else {}
        has_t = (ROOT / "data" / "podcasts" / "t" / f"{s['id']}.json").exists()
        out[s["id"]] = {
            "id": s["id"], "kind": s.get("kind", "stream"), "creator": s.get("creator"), "podcast": s["series"], "title": s["title"],
            "published": s.get("date", ""), "credit": s.get("credit"), "event": s.get("event", s["title"]),
            "youtube": s.get("youtube") or mac.get("youtube"), "seconds": mac.get("seconds"), "audio": None, "link": None, "art": None,
            "status": "transcribed" if has_t and mac.get("status") == "transcribed"
                      and (not s.get("youtube") or mac.get("youtube") == s["youtube"]) else (mac.get("status") or "new"), "error": mac.get("error"),
            "transcribed": mac.get("transcribed"),
        }
    return out

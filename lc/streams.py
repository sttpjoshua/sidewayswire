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
    f = DIR / "streams.json"
    return json.loads(f.read_text())["streams"] if f.exists() else []


def episodes() -> dict:
    out = {}
    for s in registry():
        mf = DIR / "mac" / f"{s['id']}.json"
        mac = json.loads(mf.read_text()) if mf.exists() else {}
        has_t = (ROOT / "data" / "podcasts" / "t" / f"{s['id']}.json").exists()
        out[s["id"]] = {
            "id": s["id"], "kind": "stream", "podcast": s["series"], "title": s["title"],
            "published": s.get("date", ""), "credit": s.get("credit"), "event": s.get("event", s["title"]),
            "youtube": mac.get("youtube"), "seconds": mac.get("seconds"), "audio": None, "link": None, "art": None,
            "status": "transcribed" if has_t else (mac.get("status") or "new"), "error": mac.get("error"),
            "transcribed": mac.get("transcribed"),
        }
    return out

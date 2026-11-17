"""Writes docs/status.json for the dashboard and sends the daily Telegram summary."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import queue as q

ROOT = Path(__file__).resolve().parent.parent


def podcast_status() -> dict:
    d = ROOT / "data" / "podcasts"
    if not (d / "episodes.json").exists():
        return {"feeds": {}, "episodes": []}
    ix = json.loads((d / "episodes.json").read_text())
    from . import streams
    allep = {**ix["episodes"], **streams.episodes()}
    eps = []
    for e in sorted(allep.values(), key=lambda e: e["published"] or "", reverse=True)[:60]:
        mf = d / "moments" / f"{e['id']}.json"
        moments = json.loads(mf.read_text()) if mf.exists() else []
        eps.append({k: e.get(k) for k in ("id", "podcast", "title", "published", "status", "youtube",
                                          "audio", "link", "art", "seconds", "error", "transcribed", "tries", "kind", "credit", "event")}
                   | {"has_transcript": (d / "t" / f"{e['id']}.txt").exists(),
                      "moments": [{k: m.get(k) for k in ("start", "end", "kind", "guest", "topic", "quote",
                                                         "why", "status", "clip", "mode", "wait_video")} | {"split": bool(m.get("split"))} for m in moments]})
    feeds = {n: {k: f.get(k) for k in ("title", "episodes", "error", "ok")} for n, f in ix["feeds"].items()}
    return {"feeds": feeds, "episodes": eps}


def run(folder: Path = q.QUEUE, out: Path = ROOT / "docs" / "status.json") -> dict:
    posts = q.load(folder=folder)
    inbox = ROOT / "data" / "inbox.json"
    ib = json.loads(inbox.read_text()) if inbox.exists() else {}
    stories = ib.get("stories", [])
    def clip_title(p):            # podcast clips: the headline of the moment
        if p.get("title") or p.get("kind") != "podcast_clip":
            return p.get("title")
        try:
            _, ep, i = p["id"].split("-")
            return json.loads((ROOT / "data" / "podcasts" / "moments" / f"{ep}.json").read_text())[int(i)].get("topic")
        except Exception:
            return None
    keep = ("id", "kind", "status", "post_at", "posted_at", "caption", "media", "problems", "results", "credit",
            "check", "check_reason", "source", "platforms", "created", "built", "want_at", "video", "tags", "missing_handles", "caption_by", "format")
    status = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "counts": dict(Counter(p.get("status", "draft") for p in posts)),
        "collected": ib.get("updated"),
        "instagram": ib.get("instagram", False),
        "sources": ib.get("sources", []),
        "inbox": [{k: s.get(k) for k in ("title", "series", "buzz", "published", "items")} for s in stories[:80]],
        "podcasts": podcast_status(),
        "posts": [{k: p.get(k) for k in keep} | {"media": [m.removeprefix("docs/") for m in p.get("media") or []],
                                                 "video": (p.get("video") or "").removeprefix("docs/") or None,
                                                 "title": clip_title(p)}
                  for p in sorted(posts, key=lambda p: p.get("post_at") or p.get("built") or p.get("created") or "",
                                  reverse=True)[:300]],
        "channels": json.loads((ROOT / "data" / "channels.json").read_text()) if (ROOT / "data" / "channels.json").exists() else {},
    }
    out.write_text(json.dumps(status, indent=1, ensure_ascii=False), encoding="utf-8")
    return status["counts"]


if __name__ == "__main__":
    print(run())

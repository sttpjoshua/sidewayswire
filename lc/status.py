"""Writes docs/status.json for the dashboard and sends the daily Telegram summary."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import queue as q

ROOT = Path(__file__).resolve().parent.parent


def run(folder: Path = q.QUEUE, out: Path = ROOT / "docs" / "status.json") -> dict:
    posts = q.load(folder=folder)
    inbox = ROOT / "data" / "inbox.json"
    ib = json.loads(inbox.read_text()) if inbox.exists() else {}
    stories = ib.get("stories", [])
    keep = ("id", "kind", "status", "post_at", "posted_at", "caption", "media", "problems", "results", "credit")
    status = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "counts": dict(Counter(p.get("status", "draft") for p in posts)),
        "collected": ib.get("updated"),
        "instagram": ib.get("instagram", False),
        "sources": ib.get("sources", []),
        "inbox": [{k: s.get(k) for k in ("title", "series", "buzz", "published", "items")} for s in stories[:80]],
        "posts": [{k: p.get(k) for k in keep} | {"media": [m.removeprefix("docs/") for m in p.get("media", [])]}
                  for p in sorted(posts, key=lambda p: p.get("post_at") or p.get("built") or "", reverse=True)[:60]],
    }
    out.write_text(json.dumps(status, indent=1, ensure_ascii=False), encoding="utf-8")
    return status["counts"]


if __name__ == "__main__":
    print(run())

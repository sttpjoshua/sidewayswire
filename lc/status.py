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
    stories = json.loads(inbox.read_text())["stories"] if inbox.exists() else []
    keep = ("id", "kind", "status", "post_at", "posted_at", "caption", "media", "problems", "results", "credit")
    status = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "counts": dict(Counter(p.get("status", "draft") for p in posts)),
        "inbox": [{"title": s["title"], "series": s["series"], "buzz": s["buzz"]} for s in stories[:30]],
        "posts": [{k: p.get(k) for k in keep} | {"media": [m.removeprefix("docs/") for m in p.get("media", [])]}
                  for p in sorted(posts, key=lambda p: p.get("post_at") or p.get("built") or "", reverse=True)[:60]],
    }
    out.write_text(json.dumps(status, indent=1, ensure_ascii=False), encoding="utf-8")
    return status["counts"]


if __name__ == "__main__":
    print(run())

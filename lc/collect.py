"""The collector: runs every 15 minutes (cron-job.org -> GitHub Actions).

1. Loads data/sources.csv and picks the sources that are due.
2. Reads site feeds, YouTube feeds and Instagram (Business Discovery).
3. Stores new items in data/lc.db, grouped into stories with a buzz count.
4. Writes data/inbox.json: the new stories the hourly editor task looks at.

Every source is wrapped in its own try/except: one broken source never
stops the run. Failures are counted and reported in the daily Telegram summary.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import feeds, sources
from .store import Store

DATA = Path(__file__).resolve().parent.parent / "data"


def run(sources_csv: Path = DATA / "sources.csv", db: Path = DATA / "lc.db",
        inbox: Path = DATA / "inbox.json", ig=None, fetch=None) -> dict:
    """fetch: optional function(url) -> text, so tests can run without internet."""
    store = Store(str(db))
    all_sources = sources.load(sources_csv)
    due = sources.due(all_sources, store.minutes_since_checks())
    report = {"checked": 0, "new_items": 0, "errors": []}

    for s in due:
        try:
            found = []
            feed_url = feeds.SITE_FEEDS.get(s.name)
            if feed_url:
                found += feeds.parse(fetch(feed_url) if fetch else feed_url, s.name, s.series)
            if s.web and "channel_id=" in s.web:
                url = feeds.YOUTUBE_FEED.format(s.web.split("channel_id=")[1])
                found += feeds.parse(fetch(url) if fetch else url, s.name, s.series)
            if ig and s.ig_username and not store.is_blocked(s.ig_username):
                for m in ig.recent_media(s.ig_username):
                    m["series"] = s.series
                    found.append(m)
            for item in found:
                _, is_new = store.add(**{k: item[k] for k in
                                         ("source", "series", "kind", "title", "url", "published",
                                          "media_url", "media_type", "raw")})
                report["new_items"] += int(is_new)
            store.touch(s.name)
            report["checked"] += 1
        except Exception as e:  # one source failing must not stop the run
            report["errors"].append({"source": s.name, "error": str(e)[:300]})

    stories = []
    for st in store.new_stories():
        items = store.story_items(st["id"])
        stories.append({
            "id": st["id"], "title": st["title"], "series": st["series"], "buzz": st["buzz"],
            "first_seen": st["first_seen"],
            "items": [{"source": i["source"], "title": i["title"], "url": i["url"],
                       "media_url": i["media_url"], "media_type": i["media_type"]} for i in items],
        })
    inbox.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(),
                                 "stories": stories}, indent=1, ensure_ascii=False))
    report["inbox"] = len(stories)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))
    sys.exit(0)

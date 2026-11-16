"""The collector: runs every 15 minutes on GitHub Actions.

1. Reads every website and YouTube channel in feeds.WATCH.
2. Reads Instagram of every source with a handle, once the Meta app exists
   (secrets IG_USER_ID and IG_TOKEN), respecting each source's check interval.
3. Stores new items in data/lc.db, grouped into stories with a buzz count.
4. Writes data/inbox.json: the stories the editor and the dashboard look at.

Every source is wrapped in its own try/except: one broken source never
stops the run. Problems are listed on the dashboard.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import feeds, sources
from .store import Store

DATA = Path(__file__).resolve().parent.parent / "data"
MAX_AGE = timedelta(days=21)          # older items are not news any more


def _store_items(store: Store, items: list[dict], report: dict):
    now = datetime.now(timezone.utc)
    for item in items:
        if not item.get("title") or now - item["published"] > MAX_AGE:
            continue
        _, is_new = store.add(**{k: item[k] for k in
                                 ("source", "series", "kind", "title", "url", "published",
                                  "media_url", "media_type", "raw")})
        report["new_items"] += int(is_new)


def run(sources_csv: Path = DATA / "sources.csv", db: Path = DATA / "lc.db",
        inbox: Path = DATA / "inbox.json", ig=None, fetch=None, watch=None) -> dict:
    """fetch: optional function(url) -> text, so tests can run without internet."""
    store = Store(str(db))
    report = {"checked": 0, "new_items": 0, "errors": [], "targets": []}
    cache = feeds.load_cache() if fetch is None else {}

    # 1. websites and YouTube
    for source, series, url, keyword in (watch if watch is not None else feeds.WATCH):
        try:
            items = feeds.read_target(source, series, url, keyword, cache, fetch)
            _store_items(store, items, report)
            report["checked"] += 1
            report["targets"].append({"source": source, "url": url, "ok": True, "items": len(items),
                                      "how": cache.get(url, {}).get("kind")})
        except Exception as e:
            report["errors"].append({"source": source, "url": url, "error": str(e)[:200]})
            report["targets"].append({"source": source, "url": url, "ok": False, "error": str(e)[:120]})
    if fetch is None:
        feeds.save_cache(cache)

    # 2. Instagram (only once the Meta app and token exist)
    if ig and sources_csv.exists():
        due = sources.due(sources.load(sources_csv), store.minutes_since_checks())
        for s in due:
            if not s.ig_username or store.is_blocked(s.ig_username):
                continue
            try:
                found = ig.recent_media(s.ig_username)
                for m in found:
                    m["series"] = s.series
                _store_items(store, found, report)
                store.touch(s.name)
                report["checked"] += 1
            except Exception as e:
                report["errors"].append({"source": s.name, "url": f"instagram @{s.ig_username}",
                                         "error": str(e)[:200]})

    # 3. inbox for the editor and the dashboard
    stories = []
    for st in store.new_stories(80):
        items = store.story_items(st["id"])
        stories.append({
            "id": st["id"], "title": st["title"], "series": st["series"], "buzz": st["buzz"],
            "first_seen": st["first_seen"],
            "published": max(i["published"] for i in items),
            "items": [{"source": i["source"], "title": i["title"], "url": i["url"], "kind": i["kind"],
                       "published": i["published"], "media_url": i["media_url"],
                       "media_type": i["media_type"]} for i in items],
        })
    stories.sort(key=lambda s: (s["buzz"] > 1, s["published"]), reverse=True)
    inbox.write_text(json.dumps({"updated": datetime.now(timezone.utc).isoformat(),
                                 "stories": stories, "sources": report["targets"],
                                 "instagram": bool(ig)}, indent=1, ensure_ascii=False))
    report["inbox"] = len(stories)
    return report


if __name__ == "__main__":
    ig = None
    if os.environ.get("IG_TOKEN") and os.environ.get("IG_USER_ID"):
        from .instagram import Instagram
        ig = Instagram()
    rep = run(ig=ig)
    print(json.dumps({k: v for k, v in rep.items() if k != "targets"}, indent=1, ensure_ascii=False))
    for t in rep["targets"]:
        print(("OK  " if t["ok"] else "ERR ") + t["source"] + " · " + t["url"] + " · " + str(t.get("items", t.get("error"))))

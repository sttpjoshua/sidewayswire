"""Reading feeds: websites (RSS/Atom) and YouTube channels.

YouTube offers a free feed per channel:
    https://www.youtube.com/feeds/videos.xml?channel_id=<id>
WordPress sites such as news.formulad.com have /feed/.
"""
from __future__ import annotations

from datetime import datetime, timezone
from time import mktime

import feedparser

YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"

# Known feeds. Filled further in build week 2 from the sources sheet.
SITE_FEEDS = {
    "Formula DRIFT": "https://news.formulad.com/feed/",
    "Drifted.com": "https://www.drifted.com/feed/",
}


def _when(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            return datetime.fromtimestamp(mktime(entry[key]), tz=timezone.utc)
    return datetime.now(timezone.utc)


def parse(feed_text_or_url: str, source: str, series: str, kind: str = "article") -> list[dict]:
    """Parse a feed (URL or raw XML) into store-ready dicts."""
    fp = feedparser.parse(feed_text_or_url)
    out = []
    for e in fp.entries:
        media_url = None
        if e.get("media_thumbnail"):
            media_url = e["media_thumbnail"][0].get("url")
        out.append({
            "source": source, "series": series,
            "kind": "video" if "yt_videoid" in e else kind,
            "title": e.get("title", "").strip(), "url": e.get("link"),
            "published": _when(e), "media_url": media_url,
            "media_type": "VIDEO" if "yt_videoid" in e else None,
            "raw": {"summary": e.get("summary", "")[:2000], "video_id": e.get("yt_videoid")},
        })
    return out

"""Reading websites and YouTube channels.

Every target in WATCH is resolved once (on GitHub, which has full internet):
- a YouTube link or @handle -> the channel's free RSS feed
- a website -> its RSS/Atom feed (from the page header, or /feed, /rss ...)
- a website without any feed -> the page itself, read for article links
Results are cached in data/feeds.json so later runs go straight to the feed.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from time import mktime
from urllib.parse import urljoin, urlparse

import feedparser
import requests

YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
UA = {"User-Agent": "Mozilla/5.0 (compatible; SidewaysWireBot/1.0; +https://sttpjoshua.github.io/sidewayswire/)",
      "Accept-Language": "en"}
CACHE = Path(__file__).resolve().parent.parent / "data" / "feeds.json"

# What we watch besides Instagram. keyword: only keep items that mention it
# (for general sites that also post about other things).
WATCH = [
    # source name (as in sources.csv), series, url, keyword
    ("Formula DRIFT", "FD", "https://news.formulad.com", None),
    # Sites that block bots are read through Google News (gnews: + search terms).
    ("RACER", "FD", "gnews:site:racer.com \"formula drift\"", "drift"),
    ("Drifted.com", "FD + DM", "gnews:site:drifted.com", None),
    ("Google News", "FD", "gnews:\"Formula Drift\"", "drift"),
    ("Google News", "DM", "gnews:\"Drift Masters\"", "drift"),
    ("Formula DRIFT", "FD", "https://www.youtube.com/@FormulaDRIFT", None),
    ("Drift Masters", "DM", "https://www.youtube.com/@DriftMastersGrandPrix", None),
    ("Auto Partner", "DM", "https://autopartner.com/en/category/events", "drift"),
    ("Conor Shanahan", "FD + DM", "https://www.youtube.com/@TheShanahans", None),
    ("Aurimas Bakchis", "FD", "https://www.youtube.com/fealsuspension", None),
    ("Matt Field", "FD", "https://www.youtube.com/@mattfield777", None),
    ("Adam LZ", "FD", "https://www.youtube.com/@AdamLZ", None),
    ("D1 Grand Prix (D1GP)", "D1GP", "https://d1gp.co.jp", None),
    ("auto sport web · drift", "D1GP", "https://www.as-web.jp/drift", None),
    ("Nürburgring Drift Cup", "NDC", "https://nuerburgring.de/news", "drift"),
    ("Gatebil", "Gatebil", "https://gatebil.no", "drift"),
    # Off-season: the stories are new cars, liveries, team moves and builds, not results.
    ("Drift Masters", "DM", "https://dm.gp/articles/", None),
    ("Speedhunters", "FD + DM", "gnews:site:speedhunters.com drift", "drift"),
    ("Google News", "FD + DM", "gnews:drift \"new car\" OR livery OR \"build\" Formula Drift OR \"Drift Masters\"", "drift"),
    ("Google News", "FD + DM", "gnews:drift driver signs OR joins OR \"switches to\" OR announces 2027", "drift"),
    ("Google News", "FD", "gnews:\"James Deane\" OR \"Vaughn Gittin\" OR \"Chelsea DeNofa\" OR \"Ryan Tuerck\" drift", "drift"),
    ("Google News", "D1GP", "gnews:\"D1GP\" OR \"D1 Grand Prix\" drift", "drift"),
]


def _get(url: str) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    return r


def _is_feed(text: str) -> bool:
    head = text[:600].lower()
    return "<rss" in head or "<feed" in head or "<rdf" in head


def gnews(query: str) -> str:
    from urllib.parse import quote
    return f"https://news.google.com/rss/search?q={quote(query + ' when:14d')}&hl=en-US&gl=US&ceid=US:en"


def resolve(url: str) -> dict:
    """Find how to read a target. Returns {"kind": "feed"|"page", "url": ...}."""
    if url.startswith("gnews:"):
        return {"kind": "feed", "url": gnews(url[6:])}
    host = urlparse(url).netloc
    if "youtube.com" in host:
        html = _get(url).text
        m = (re.search(r'"channelId":"(UC[\w-]{22})"', html)
             or re.search(r'youtube\.com/channel/(UC[\w-]{22})', html)
             or re.search(r'"externalId":"(UC[\w-]{22})"', html))
        if not m:
            raise ValueError("no channel id found on the YouTube page")
        return {"kind": "feed", "url": YOUTUBE_FEED.format(m.group(1))}
    r = _get(url)
    if _is_feed(r.text):
        return {"kind": "feed", "url": url}
    for m in re.finditer(r'<link[^>]+>', r.text, re.I):
        tag = m.group(0)
        if re.search(r'type=["\']application/(rss|atom)\+xml', tag, re.I):
            href = re.search(r'href=["\']([^"\']+)', tag)
            if href:
                return {"kind": "feed", "url": urljoin(url, unescape(href.group(1)))}
    base = url.rstrip("/")
    for tail in ("/feed/", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml"):
        try:
            t = _get(base + tail)
            if _is_feed(t.text):
                return {"kind": "feed", "url": base + tail}
        except Exception:
            pass
    return {"kind": "page", "url": url}


def _when(entry) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            return datetime.fromtimestamp(mktime(entry[key]), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _image(entry) -> str | None:
    for key in ("media_thumbnail", "media_content"):
        if entry.get(key):
            return entry[key][0].get("url")
    for l in entry.get("links", []):
        if l.get("type", "").startswith("image/"):
            return l.get("href")
    m = re.search(r'<img[^>]+src=["\']([^"\']+)', entry.get("summary", "") or "")
    return m.group(1) if m else None


def parse(feed_text_or_url: str, source: str, series: str, kind: str = "article") -> list[dict]:
    """Parse a feed (URL or raw XML) into store-ready dicts."""
    fp = feedparser.parse(feed_text_or_url)
    out = []
    for e in fp.entries:
        video = "yt_videoid" in e
        title = unescape(e.get("title", "")).strip()
        publisher = (e.get("source") or {}).get("title")
        if publisher and title.endswith(" - " + publisher):
            title = title[: -len(publisher) - 3]
        out.append({
            "source": f"{source} · {publisher}" if publisher and source == "Google News" else source,
            "series": series,
            "kind": "video" if video else kind,
            "title": title, "url": e.get("link"),
            "published": _when(e), "media_url": _image(e),
            "media_type": "VIDEO" if video else ("IMAGE" if _image(e) else None),
            "raw": {"summary": re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")[:1500],
                    "video_id": e.get("yt_videoid")},
        })
    return out


def parse_page(html: str, url: str, source: str, series: str) -> list[dict]:
    """For sites without a feed: article links with a real headline on the page."""
    out, seen = [], set()
    host = urlparse(url).netloc
    for m in re.finditer(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html, re.S | re.I):
        href = urljoin(url, unescape(m.group(1)))
        inner = m.group(2)
        head = re.search(r"<h[1-4][^>]*>(.*?)</h[1-4]>", inner, re.S | re.I)   # card links: use the headline
        text = unescape(re.sub(r"<[^>]+>|\s+", " ", head.group(1) if head else inner)).strip()
        text = re.sub(r"\s+", " ", text)
        if urlparse(href).netloc != host or href in seen or len(text) < 25 or len(text) > 200:
            continue
        path = urlparse(href).path
        if path.count("/") < 2 and not re.search(r"\d", path):
            continue
        seen.add(href)
        out.append({"source": source, "series": series, "kind": "article", "title": text, "url": href,
                    "published": datetime.now(timezone.utc), "media_url": None, "media_type": None,
                    "raw": {"from_page": url}})
    return out[:30]


def load_cache() -> dict:
    return json.loads(CACHE.read_text()) if CACHE.exists() else {}


def save_cache(cache: dict):
    CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False))


def read_target(source: str, series: str, url: str, keyword: str | None, cache: dict,
                fetch=None) -> list[dict]:
    """Read one target, resolving (and caching) its feed first."""
    info = cache.get(url)
    if not info or info.get("error"):
        try:
            info = resolve(url) if fetch is None else {"kind": "feed", "url": url}
        except Exception as e:
            cache[url] = {"error": str(e)[:200], "checked": datetime.now(timezone.utc).isoformat()}
            raise
        cache[url] = info
    if info["kind"] == "feed":
        items = parse(fetch(info["url"]) if fetch else _get(info["url"]).text, source, series)
    else:
        items = parse_page(fetch(info["url"]) if fetch else _get(info["url"]).text, info["url"], source, series)
    if keyword:
        items = [i for i in items if keyword in (i["title"] + " " + i["raw"].get("summary", "")).lower()]
    cache[url] |= {"ok": datetime.now(timezone.utc).isoformat(), "last_count": len(items)}
    return items

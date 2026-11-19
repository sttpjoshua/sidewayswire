"""The post queue: one JSON file per post in queue/.

Status flow:  draft -> ready -> posted
                    -> check (waits for Joshua on Telegram or the dashboard) -> ready / skipped
              approved (set on the dashboard, optional want_at) -> ready
A post file:
  {"id", "kind", "story", "slides": [{"template", "data"}], "caption",
   "platforms": ["instagram","facebook"], "check": false, "credit": "@handle",
   "status", "post_at", "media": [paths], "problems": [], "results": {}}
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "queue"

# Posting rhythm. Times in Amsterdam time; the audience is worldwide, so the
# slots cover the European evening and the American afternoon/evening.
SLOTS = ["08:30", "12:30", "17:30", "20:30", "23:00"]
MAX_PER_DAY = 5          # race weekends: results skip the slots and post at once
MIN_GAP_MIN = 90
URGENT = {"result", "champion", "quali", "livestream", "breaking"}   # breaking: kop-post, out within hours
TZ = ZoneInfo("Europe/Amsterdam")
START = datetime(2026, 12, 1, 0, 0, tzinfo=TZ)   # Joshua starts posting in December: nothing is planned before this
# Content calendar: what each slot is for, so a day mixes reels and posts.
# reel_pod = podcast clip, reel_live = livestream moment or battle, post = news/carousel, any = whatever is next.
SLOT_USE = {"08:30": "post", "12:30": "reel_pod", "17:30": "reel_live", "20:30": "any", "23:00": "reel_pod"}


def use_of(kind: str) -> str:
    return {"podcast_clip": "reel_pod", "stream_clip": "reel_live", "battle_reel": "reel_live"}.get(kind, "post")


def load(status: str | None = None, folder: Path = QUEUE) -> list[dict]:
    posts = []
    for f in sorted(folder.glob("*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))
        if status is None or p.get("status", "draft") == status:
            posts.append(p)
    return posts


def save(post: dict, folder: Path = QUEUE):
    folder.mkdir(exist_ok=True)
    (folder / f"{post['id']}.json").write_text(
        json.dumps(post, indent=1, ensure_ascii=False), encoding="utf-8")


def next_slot(posts: list[dict], kind: str, now: datetime | None = None) -> datetime:
    """Pick the moment for a new post. Urgent kinds go out at once (with a
    small gap after the last post); the rest take the next free slot."""
    now = max(now or datetime.now(timezone.utc), START)
    taken = sorted(datetime.fromisoformat(p["post_at"]) for p in posts
                   if p.get("post_at") and p.get("status") in ("ready", "posted"))
    if kind in URGENT:
        near = [t for t in taken if abs((t - now).total_seconds()) < 600]
        return max(near) + timedelta(minutes=10) if near else now
    day = now.astimezone(TZ).date()
    use = use_of(kind)
    # First the slots meant for this kind of content, then (if those are full for two months) any slot.
    for strict in (True, False):
        for add in range(0, 62):
            d = day + timedelta(days=add)
            todays = [t for t in taken if t.astimezone(TZ).date() == d]
            if len(todays) >= MAX_PER_DAY:
                continue
            for s in SLOTS:
                if strict and SLOT_USE.get(s, "any") not in (use, "any"):
                    continue
                h, m = map(int, s.split(":"))
                t = datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).astimezone(timezone.utc)
                if t <= now:
                    continue
                if all(abs((t - o).total_seconds()) >= MIN_GAP_MIN * 60 for o in taken):
                    return t
    return now + timedelta(days=62)

"""Reach and growth numbers from the platforms, for the Statistieken page.

Every 6 hours (called from run.yml) it stores one snapshot per day in docs/stats.json:
- Instagram: followers, media count, reach / views / profile views of the day, and per post we placed
  reach, views, likes, comments, shares, saves;
- Facebook page: followers, and per post reactions, comments, shares.
TikTok and YouTube follow once their apps are approved. Without a key it does nothing.

    python -m lc.stats
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import queue as q

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "stats.json"
GRAPH = "https://graph.facebook.com/v21.0"
EVERY_H = 6


def _get(path: str, token: str, **params) -> dict:
    params["access_token"] = token
    r = requests.get(f"{GRAPH}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _ig_day(a: dict) -> dict:
    out = {}
    try:
        u = _get(a["ig_user_id"], a["ig_token"], fields="followers_count,media_count")
        out.update(followers=u.get("followers_count"), media=u.get("media_count"))
    except Exception as e:
        out["error"] = str(e)[:120]
    for metric in ("reach", "views", "profile_views", "accounts_engaged", "total_interactions"):
        try:
            d = _get(f"{a['ig_user_id']}/insights", a["ig_token"], metric=metric, period="day",
                     metric_type="total_value")
            v = (d.get("data") or [{}])[0]
            out[metric] = (v.get("total_value") or {}).get("value", (v.get("values") or [{}])[-1].get("value"))
        except Exception:
            continue
    return out


def _ig_post(mid: str, token: str) -> dict:
    out = {}
    for metric in ("reach", "views", "likes", "comments", "shares", "saved", "total_interactions"):
        try:
            d = _get(f"{mid}/insights", token, metric=metric)
            out[metric] = (d.get("data") or [{}])[0].get("values", [{}])[0].get("value")
        except Exception:
            continue
    return out


def _fb_post(pid: str, token: str) -> dict:
    try:
        d = _get(pid, token, fields="shares,reactions.summary(true).limit(0),comments.summary(true).limit(0)")
        return {"reactions": (d.get("reactions") or {}).get("summary", {}).get("total_count"),
                "comments": (d.get("comments") or {}).get("summary", {}).get("total_count"),
                "shares": (d.get("shares") or {}).get("count", 0)}
    except Exception:
        return {}


REEL_KINDS = {"stream_clip", "podcast_clip", "battle_reel", "vlog_clip", "weekly"}
MIN_POSTS = 5             # a format needs this many measured posts before the system acts on it


def format_of(p: dict) -> str:
    """The kind of post as Joshua thinks about it: the kop-post type, or reel/news."""
    if p.get("hook"):
        return (p["hook"] or {}).get("type") or "hook"
    if p.get("kind") in REEL_KINDS:
        return "reel"
    return p.get("kind") or "post"


def by_format(posts: dict) -> dict:
    """Average likes, comments and shares per post, per format, over both platforms."""
    agg = {}
    for row in posts.values():
        f = row.get("format") or "post"
        ig, fb = row.get("instagram") or {}, row.get("facebook") or {}
        if not ig and not fb:
            continue
        a = agg.setdefault(f, {"posts": 0, "likes": 0, "comments": 0, "shares": 0})
        a["posts"] += 1
        a["likes"] += (ig.get("likes") or 0) + (fb.get("reactions") or 0)
        a["comments"] += (ig.get("comments") or 0) + (fb.get("comments") or 0)
        a["shares"] += (ig.get("shares") or 0) + (fb.get("shares") or 0)
    for a in agg.values():
        n = a["posts"]
        a.update({k: round(a[k] / n, 1) for k in ("likes", "comments", "shares")})
        a["engagement"] = round(a["likes"] + 3 * a["comments"] + 5 * a["shares"], 1)   # a comment or share counts more
        a["enough"] = n >= MIN_POSTS
    return agg


def run(force: bool = False) -> dict:
    old = json.loads(OUT.read_text()) if OUT.exists() else {"days": {}, "posts": {}}
    now = datetime.now(timezone.utc)
    if not force and old.get("updated") and now - datetime.fromisoformat(old["updated"]) < timedelta(hours=EVERY_H):
        return {"skipped": True}
    try:
        from .meta import accounts
        a = accounts()
    except Exception as e:
        return {"error": str(e)[:200]}
    if not a:
        return {"no_key": True}
    day = now.date().isoformat()
    snap = old["days"].get(day, {})
    if a.get("ig_user_id"):
        snap["instagram"] = _ig_day(a)
    if a.get("page_id"):
        try:
            p = _get(a["page_id"], a["page_token"], fields="followers_count,fan_count")
            snap["facebook"] = {"followers": p.get("followers_count") or p.get("fan_count")}
        except Exception as e:
            snap["facebook"] = {"error": str(e)[:120]}
    try:                                             # YouTube: subscribers and total views, once it is linked
        from . import youtube as yt
        if (yt.DIR / "token.enc").exists():
            i = yt.info()
            snap["youtube"] = {"subscribers": int(i.get("subscribers") or 0)}
    except Exception as e:
        snap["youtube"] = {"error": str(e)[:120]}
    old["days"][day] = snap
    # posts placed in the last 30 days
    for p in q.load("posted"):
        if not p.get("posted_at") or now - datetime.fromisoformat(p["posted_at"]) > timedelta(days=30):
            continue
        res, row = p.get("results") or {}, old["posts"].get(p["id"], {})
        row.update(title=p.get("title") or (p.get("caption") or "").split("\n")[0][:80], kind=p.get("kind"),
                   format=format_of(p),
                   posted_at=p["posted_at"], score=p.get("score"), people=p.get("people"))
        ig, fb = res.get("instagram"), res.get("facebook")
        if ig and str(ig).isdigit() and a.get("ig_token"):
            row["instagram"] = _ig_post(str(ig), a["ig_token"])
        if fb and "ERROR" not in str(fb) and fb != "dry-run" and a.get("page_token"):
            row["facebook"] = _fb_post(str(fb), a["page_token"])
        old["posts"][p["id"]] = row
    old["by_format"] = by_format(old["posts"])
    old["updated"] = now.isoformat()
    OUT.write_text(json.dumps(old, indent=1, ensure_ascii=False))
    return {"day": day, "posts": len(old["posts"])}


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

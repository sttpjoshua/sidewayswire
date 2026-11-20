"""Posts everything in the queue whose time has come.

LC_DRY_RUN=1 (the default until Joshua switches it off) does everything
except the real post: it logs what would have gone out. That is the test week.
PAGES_URL is the public address of docs/ (GitHub Pages).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import queue as q
from .instagram import GRAPH, Instagram
from .telegram import Telegram

ROOT = Path(__file__).resolve().parent.parent


def media_urls(post: dict) -> list[str]:
    """Site address when the file is staged on the site (Meta prefers that), else the release address."""
    from . import mediastore
    base = os.environ.get("PAGES_URL", "").rstrip("/")
    return [f"{base}/{m.removeprefix('docs/')}" if (ROOT / m).exists() else mediastore.url(m) for m in post["media"]]


def post_facebook(urls: list[str], caption: str) -> str:
    from .meta import accounts
    a = accounts()
    page, token = a["page_id"], a["page_token"]
    if urls[0].endswith(".mp4"):
        r = requests.post(f"{GRAPH}/{page}/videos", timeout=300,
                          data={"file_url": urls[0], "description": caption, "access_token": token})
        r.raise_for_status()
        return r.json()["id"]
    if len(urls) == 1:
        r = requests.post(f"{GRAPH}/{page}/photos", timeout=60,
                          data={"url": urls[0], "caption": caption, "access_token": token})
        r.raise_for_status()
        return r.json()["id"]
    ids = []
    for u in urls:
        r = requests.post(f"{GRAPH}/{page}/photos", timeout=60,
                          data={"url": u, "published": "false", "access_token": token})
        r.raise_for_status()
        ids.append(r.json()["id"])
    data = {"message": caption, "access_token": token}
    for i, mid in enumerate(ids):
        data[f"attached_media[{i}]"] = json.dumps({"media_fbid": mid})
    r = requests.post(f"{GRAPH}/{page}/feed", data=data, timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def _urls(post: dict, platform: str) -> list[str]:
    """TikTok and YouTube get the short version (max 30 s, starts with the action) when there is one."""
    if platform in ("tiktok", "youtube") and post.get("short"):
        return media_urls({"media": [post["short"]]})
    return media_urls(post)


def run(folder: Path = q.QUEUE, now: datetime | None = None) -> dict:
    """Posts, per platform, what is due in the post's plan (see planner.py)."""
    from . import planner, tiktok
    now = now or datetime.now(timezone.utc)
    dry = os.environ.get("LC_DRY_RUN", "1") != "0"
    tg, ig = Telegram(), Instagram()
    report = {"posted": 0, "dry_run": dry, "errors": []}
    for p in q.load("ready", folder):
        plan = p.get("plan") or ({pl: p["post_at"] for pl in p.get("platforms", [])} if p.get("post_at") else {})
        due = [pl for pl, t in plan.items() if datetime.fromisoformat(t) <= now and pl not in (p.get("results") or {})]
        if not due:
            continue
        results = dict(p.get("results") or {})
        caps = p.get("captions") or {}
        for platform in due:
            caption = caps.get(platform) or p["caption"]
            urls = _urls(p, platform)
            try:
                if dry:
                    results[platform] = "dry-run"
                elif platform == "instagram":
                    is_video = urls[0].endswith(".mp4")
                    collab = p.get("collaborators") or []
                    results[platform] = (ig.post_reel(urls[0], caption, collaborators=collab) if is_video
                                         else ig.post_image(urls[0], caption, collaborators=collab) if len(urls) == 1
                                         else ig.post_carousel(urls[:10], caption, collaborators=collab))
                elif platform == "facebook":
                    results[platform] = post_facebook(urls, caption)
                elif platform == "tiktok" and tiktok.connected():
                    # Until TikTok has audited the app, posts are private (settings.tiktok_privacy).
                    results[platform] = tiktok.post_for(p, caption)
                else:
                    # YouTube switches on after its audit; until then it is not 'connected'
                    # and the planner does not plan it once LC_DRY_RUN is off.
                    results[platform] = "waiting for platform audit"
            except Exception as e:
                results[platform] = f"ERROR {str(e)[:200]}"
                report["errors"].append({"post": p["id"], "platform": platform, "error": str(e)[:200]})
            report["posted"] += 1
        p["results"] = results
        p.setdefault("posted_at", now.isoformat())
        if not planner.remaining(p):
            p.update(status="posted", posted_at=now.isoformat())
        q.save(p, folder)
    if report["errors"] and tg.on:
        tg.text("Sideways Wire: posten mislukt\n" + json.dumps(report["errors"], indent=1)[:3500])
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

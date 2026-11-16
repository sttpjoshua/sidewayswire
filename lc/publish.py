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
    base = os.environ.get("PAGES_URL", "").rstrip("/")
    return [f"{base}/{m.removeprefix('docs/')}" for m in post["media"]]


def post_facebook(urls: list[str], caption: str) -> str:
    page, token = os.environ["FB_PAGE_ID"], os.environ["FB_PAGE_TOKEN"]
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


def run(folder: Path = q.QUEUE, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    dry = os.environ.get("LC_DRY_RUN", "1") != "0"
    tg, ig = Telegram(), Instagram()
    report = {"posted": 0, "dry_run": dry, "errors": []}
    for p in q.load("ready", folder):
        if datetime.fromisoformat(p["post_at"]) > now:
            continue
        urls, results = media_urls(p), {}
        for platform in p.get("platforms", ["instagram", "facebook"]):
            try:
                if dry:
                    results[platform] = "dry-run"
                elif platform == "instagram":
                    is_video = urls[0].endswith(".mp4")
                    results[platform] = (ig.post_reel(urls[0], p["caption"]) if is_video
                                         else ig.post_image(urls[0], p["caption"]) if len(urls) == 1
                                         else ig.post_carousel(urls[:10], p["caption"]))
                elif platform == "facebook":
                    results[platform] = post_facebook(urls, p["caption"])
                else:
                    # TikTok and YouTube switch on after their audits (see the audit doc).
                    results[platform] = "waiting for platform audit"
            except Exception as e:
                results[platform] = f"ERROR {str(e)[:200]}"
                report["errors"].append({"post": p["id"], "platform": platform, "error": str(e)[:200]})
        p.update(status="posted", posted_at=now.isoformat(), results=results)
        q.save(p, folder)
        report["posted"] += 1
    if report["errors"] and tg.on:
        tg.text("Sideways Wire: posten mislukt\n" + json.dumps(report["errors"], indent=1)[:3500])
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

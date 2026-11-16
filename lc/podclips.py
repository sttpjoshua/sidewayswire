"""Turns podcast moments into clips and queues them as posts.

The editor writes data/podcasts/moments/<episode id>.json:
[
  {"start": 1834.2, "end": 1872.0,          # seconds in the episode, cut on whole sentences
   "kind": "rumor" | "quote" | "fact" | "moment",
   "guest": "JACK SHANAHAN", "topic": "A NEW CAR FOR 2027?",
   "quote": "the exact words, from the transcript",
   "why": "one line: why this is interesting for the channel",
   "credit": "@formulad", "caption": "post text with credits and hashtags",
   "status": "new"}                          # new -> clip made -> queued
]
Rumors always go to Joshua on Telegram first (check=true in the queued post).
Clips are 15 to 75 seconds.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import progress
from . import queue as q
from .clips import make_clip
from .podcasts import DIR, load_index

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"


LAYOUT = 2                 # raise when the clip design changes: unposted clips are made again
WAIT_VIDEO = 3 * 3600      # how long a YouTube episode waits for the Mac helper before we fall back to audiogram
TAG = "video-sources"


def asset_name(ep_id: str, i: int, m: dict) -> str:
    """Must match tools/mac/video_helper.py: changing start or end asks for a new video."""
    return f"{ep_id}-{i}-{int(round(float(m['start']) * 10))}-{int(round(float(m['end']) * 10))}.mp4"


def video_assets() -> tuple[dict, list]:
    """({name: download url} of the videos the Mac helper uploaded, [episode ids without a full video])."""
    import requests
    repo = os.environ.get("GITHUB_REPOSITORY", "sttpjoshua/sidewayswire")
    h = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GH_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/{TAG}", headers=h, timeout=30)
        if r.ok:
            try:
                beat = json.loads(r.json().get("body") or "{}")
            except ValueError:
                beat = {}
            seen = beat.get("seen")
            alive = bool(seen) and (datetime.now(timezone.utc) - datetime.fromisoformat(seen)).total_seconds() < 3600
            return ({a["name"]: a["browser_download_url"] for a in r.json().get("assets", [])},
                    (beat.get("no_video") or []) if alive else None)
    except Exception as e:
        print("video assets:", e)
    return {}, None


def _fetch(url: str, out: Path) -> Path:
    import requests
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for c in r.iter_content(1 << 20):
                f.write(c)
    return out


def run(limit: int = 120) -> dict:
    ix = load_index()
    report = {"clips": [], "errors": [], "waiting_for_video": []}
    assets, no_video = video_assets()
    now = datetime.now(timezone.utc)
    for mf in sorted((DIR / "moments").glob("*.json")):
        ep = ix["episodes"].get(mf.stem)
        tf = DIR / "t" / f"{mf.stem}.json"
        if not ep or not tf.exists():
            continue
        moments = json.loads(mf.read_text())
        transcript = None
        for i, m in enumerate(moments):
            pid = f"pod-{mf.stem}-{i}"
            qp = q.QUEUE / f"{pid}.json"
            post = json.loads(qp.read_text()) if qp.exists() else None
            if m.get("status") == "skipped":
                if post and post.get("status") not in ("posted", "skipped"):
                    post["status"] = "skipped"
                    q.save(post)
                continue
            name = asset_name(mf.stem, i, m)
            upgrade = (m.get("status") == "queued" and not (post and post.get("status") == "posted")
                       and ((m.get("mode") == "audiogram" and name in assets) or m.get("layout", 1) < LAYOUT))
            if not (m.get("status", "new") == "new" or upgrade) or len(report["clips"]) >= limit:
                continue
            if post and post.get("status") == "posted":
                m.update(status="error", error="this clip is already posted; add a new moment instead")
                continue
            length = float(m["end"]) - float(m["start"])
            if not 10 <= length <= 90:
                m.update(status="error", error=f"clip length {length:.0f}s, keep it 15-75 s")
                continue
            if no_video is not None and name not in assets and mf.stem not in no_video:   # Mac is alive: wait for video
                since = m.setdefault("wait_video", now.isoformat())
                if (now - datetime.fromisoformat(since)).total_seconds() < WAIT_VIDEO:
                    report["waiting_for_video"].append(pid)
                    continue                       # the Mac helper will bring the video
            transcript = transcript or json.loads(tf.read_text())
            out = MEDIA / pid / "clip.mp4"
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                progress.update(force=True, phase="clips", episode=mf.stem, title=ep["title"],
                                podcast=ep["podcast"], clip=i, pct=None)
                with tempfile.TemporaryDirectory() as tmp:
                    src = _fetch(assets[name], Path(tmp) / "src.mp4") if name in assets else None
                    res = make_clip(ep, transcript, m, str(out), photo=ep.get("art"), video_src=src)
                m.pop("wait_video", None)
                m.update(status="queued", clip=str(out.relative_to(ROOT)), mode=res["mode"], layout=LAYOUT)
                check = (m["kind"] == "rumor" or res["mode"] == "audiogram" or bool(m.get("check"))) and m.get("by") != "joshua"
                q.save({
                    "id": pid, "kind": "podcast_clip", "status": "draft", "slides": [], "title": m.get("topic"),
                    "video": str(out.relative_to(ROOT)), "caption": m.get("caption", ""),
                    "credit": m.get("credit"), "check": check,
                    "check_reason": ("gerucht uit een podcast" if m["kind"] == "rumor"
                                     else "namen nakijken" if m.get("check")
                                     else "audiogram: er was geen video" if res["mode"] == "audiogram" else ""),
                    "platforms": ["instagram", "facebook", "tiktok", "youtube"],
                    "source": {"podcast": ep["podcast"], "episode": ep["title"], "start": m["start"]},
                    "created": (post or {}).get("created") or now.isoformat(),
                })
                report["clips"].append(f"{pid} ({res['mode']}{', upgraded' if upgrade else ''})")
            except Exception as e:
                m.update(status="error", error=str(e)[:200])
                report["errors"].append(f"{pid}: {e}")
        mf.write_text(json.dumps(moments, indent=1, ensure_ascii=False))
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))

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
from datetime import datetime, timezone
from pathlib import Path

from . import progress
from . import queue as q
from .clips import make_clip
from .podcasts import DIR, load_index

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"


def run(limit: int = 6) -> dict:
    ix = load_index()
    report = {"clips": [], "errors": []}
    for mf in sorted((DIR / "moments").glob("*.json")):
        ep = ix["episodes"].get(mf.stem)
        tf = DIR / "t" / f"{mf.stem}.json"
        if not ep or not tf.exists():
            continue
        moments = json.loads(mf.read_text())
        transcript = None
        for i, m in enumerate(moments):
            pid = f"pod-{mf.stem}-{i}"
            if m.get("status") == "skipped":
                qp = q.QUEUE / f"{pid}.json"
                if qp.exists():
                    post = json.loads(qp.read_text())
                    if post.get("status") not in ("posted", "skipped"):
                        post["status"] = "skipped"
                        q.save(post)
                continue
            if m.get("status", "new") != "new" or len(report["clips"]) >= limit:
                continue
            qp = q.QUEUE / f"{pid}.json"
            if qp.exists() and json.loads(qp.read_text()).get("status") == "posted":
                m.update(status="error", error="this clip is already posted; add a new moment instead")
                continue
            length = float(m["end"]) - float(m["start"])
            if not 10 <= length <= 90:
                m.update(status="error", error=f"clip length {length:.0f}s, keep it 15-75 s")
                continue
            transcript = transcript or json.loads(tf.read_text())
            out = MEDIA / pid / "clip.mp4"
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                progress.update(force=True, phase="clips", episode=mf.stem, title=ep["title"],
                                podcast=ep["podcast"], clip=i, pct=None)
                res = make_clip(ep, transcript, m, str(out), photo=ep.get("art"))
                m.update(status="queued", clip=str(out.relative_to(ROOT)), mode=res["mode"])
                q.save({
                    "id": pid, "kind": "podcast_clip", "status": "draft", "slides": [],
                    "video": str(out.relative_to(ROOT)), "caption": m.get("caption", ""),
                    "credit": m.get("credit"), "check": (m["kind"] == "rumor" or res["mode"] == "audiogram") and m.get("by") != "joshua",
                    "check_reason": ("gerucht uit een podcast" if m["kind"] == "rumor"
                                     else "audiogram: er was geen video" if res["mode"] == "audiogram" else ""),
                    "platforms": ["instagram", "facebook", "tiktok", "youtube"],
                    "source": {"podcast": ep["podcast"], "episode": ep["title"], "start": m["start"]},
                    "created": datetime.now(timezone.utc).isoformat(),
                })
                report["clips"].append(f"{pid} ({res['mode']})")
            except Exception as e:
                m.update(status="error", error=str(e)[:200])
                report["errors"].append(f"{pid}: {e}")
        mf.write_text(json.dumps(moments, indent=1, ensure_ascii=False))
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))

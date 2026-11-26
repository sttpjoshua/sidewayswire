"""Keeps the "video-sources" release under GitHub's limit of 1000 files.

The Mac helper uploads one source video per moment (lc/podclips.pieces gives the name, with start
and end in it). When a moment's start or end changes, the old file is never used again; when a clip
is posted or skipped, its source is no longer needed. At 1000 files GitHub refuses every new upload
(HTTP 422) and no new clips can be made. This removes the files nothing points to any more.

Safe by design: only files named v2-..., older than MIN_AGE_DAYS, and it stops when the moments
or queue look empty (a bad checkout must never delete everything).

    python -m lc.prune            # delete
    python -m lc.prune --dry      # only report
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

from . import queue as q
from .podcasts import DIR
from .podclips import TAG, pieces

MIN_AGE_DAYS = 2
MAX_DELETE = 400
WARN_AT = 900


def needed() -> set[str]:
    posts = {p["id"]: p.get("status") for p in q.load()}
    keep: set[str] = set()
    for mf in sorted((DIR / "moments").glob("*.json")):
        try:
            moments = json.loads(mf.read_text())
        except ValueError:
            raise RuntimeError(f"{mf.name} is unreadable: not pruning")
        for i, m in enumerate(moments):
            if m.get("status") == "skipped" or posts.get(f"pod-{mf.stem}-{i}") in ("posted", "skipped"):
                continue
            try:
                keep.update(pieces(mf.stem, i, m))
            except Exception:
                continue
    return keep


def run(dry: bool = False) -> dict:
    repo = os.environ.get("GITHUB_REPOSITORY", "sttpjoshua/sidewayswire")
    h = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {os.environ['GH_TOKEN']}"}
    api = f"https://api.github.com/repos/{repo}/releases"
    rel = requests.get(f"{api}/tags/{TAG}", headers=h, timeout=30)
    rel.raise_for_status()
    assets, page = [], 1
    while True:
        r = requests.get(f"{api}/{rel.json()['id']}/assets", headers=h, params={"per_page": 100, "page": page}, timeout=30)
        r.raise_for_status()
        assets += r.json()
        if len(r.json()) < 100:
            break
        page += 1
    if len(list((DIR / "moments").glob("*.json"))) < 5 or len(q.load()) < 20:
        return {"assets": len(assets), "deleted": 0, "note": "moments or queue look empty: not pruning"}
    keep = needed()
    cutoff = datetime.now(timezone.utc) - timedelta(days=MIN_AGE_DAYS)
    old = [a for a in assets if a["name"].startswith("v2-") and a["name"] not in keep
           and datetime.fromisoformat(a["created_at"].replace("Z", "+00:00")) < cutoff]
    old.sort(key=lambda a: a["created_at"])
    deleted, errors = 0, []
    for a in old[:MAX_DELETE]:
        if dry:
            deleted += 1
            continue
        r = requests.delete(f"{api}/assets/{a['id']}", headers=h, timeout=30)
        if r.status_code == 204:
            deleted += 1
        else:
            errors.append(f"{a['name']}: {r.status_code}")
    left = len(assets) - deleted
    rep = {"assets": len(assets), "unused": len(old), "deleted": deleted, "left": left, "dry": dry, "errors": errors[:5]}
    if left >= WARN_AT:
        rep["warning"] = f"video-sources has {left} of 1000 files: new Mac uploads will soon fail"
    return rep


if __name__ == "__main__":
    print(json.dumps(run(dry="--dry" in sys.argv), indent=1))

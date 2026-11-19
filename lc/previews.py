"""Light preview videos for the dashboard, playable on every device (also Safari on iPhone).

GitHub release files come as "download" (application/octet-stream), which iPhone Safari refuses to play.
GitHub Pages serves real video/mp4, so small 360p previews of every clip that is not posted yet live on
the Pages site of the public repo sttpjoshua/sidewayswire-media (separate from the dashboard site):
    https://sttpjoshua.github.io/sidewayswire-media/previews/<post id>.mp4
Previews of posts that were placed or skipped more than 7 days ago are removed, so the site stays small.

    python -m lc.previews [max]       # needs MEDIA_TOKEN (write access to the public repo)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import mediastore
from . import queue as q

ROOT = Path(__file__).resolve().parent.parent
REPO = mediastore.PUBLIC_REPO
BASE = f"https://sttpjoshua.github.io/{REPO.split('/')[1]}/previews/"
KINDS = ("stream_clip", "podcast_clip", "vlog_clip", "battle_reel")


def url(pid: str) -> str:
    return BASE + f"{pid}.mp4"


def make(src: Path, out: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", "scale=360:-2",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-maxrate", "380k", "-bufsize", "760k",
                    "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", str(out)], check=True)


def run(limit: int = 600) -> dict:
    tok = os.environ.get("MEDIA_TOKEN")
    if not tok:
        return {"error": "MEDIA_TOKEN ontbreekt"}
    rep = {"made": 0, "removed": 0, "errors": []}
    now = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "media"
        subprocess.run(["git", "clone", "-q", "--depth", "1", f"https://x-access-token:{tok}@github.com/{REPO}.git", str(repo)], check=True)
        pdir = repo / "previews"
        pdir.mkdir(exist_ok=True)
        (repo / ".nojekyll").touch()
        have = {f.stem for f in pdir.glob("*.mp4")}
        posts = q.load()
        keep = set()
        todo = []
        for p in posts:
            if p.get("kind") not in KINDS or not p.get("video"):
                continue
            old = p.get("status") in ("posted", "skipped") and (now - datetime.fromisoformat(
                p.get("posted_at") or p.get("built") or p.get("created") or now.isoformat())) > timedelta(days=7)
            if old:
                continue
            keep.add(p["id"])
            if p["id"] not in have or p.get("preview_of") != (p.get("built") or p.get("created")):
                todo.append(p)
        todo.sort(key=lambda p: (p.get("post_at") is None, p.get("post_at") or "", p.get("status") != "check"))
        for p in todo[:limit]:
            src = Path(tmp) / "src.mp4"
            try:
                if not mediastore.download(p["video"], src):
                    raise RuntimeError("clip niet gevonden")
                make(src, pdir / f"{p['id']}.mp4")
                p["preview"], p["preview_of"] = url(p["id"]), p.get("built") or p.get("created")
                q.save(p)
                rep["made"] += 1
            except Exception as e:
                rep["errors"].append(f"{p['id']}: {str(e)[:120]}")
            src.unlink(missing_ok=True)
            if rep["made"] and rep["made"] % 60 == 0:
                _push(repo, f"previews: {rep['made']}")
        for f in pdir.glob("*.mp4"):
            if f.stem not in keep:
                f.unlink()
                rep["removed"] += 1
        _push(repo, f"previews: {rep['made']} nieuw, {rep['removed']} weg")
        rep["size_mb"] = round(sum(f.stat().st_size for f in pdir.glob("*.mp4")) / 1e6)
    return rep


def _push(repo: Path, msg: str) -> None:
    g = ["git", "-C", str(repo), "-c", "user.name=sidewayswire-bot", "-c", "user.email=bot@users.noreply.github.com"]
    subprocess.run(g + ["add", "-A"], check=True)
    if subprocess.run(g + ["diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(g + ["commit", "-qm", msg], check=True)
    subprocess.run(g + ["push", "-q"], check=True)


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else 600), indent=1))

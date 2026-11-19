"""Media lives in GitHub releases, not on the website.

GitHub Pages allows 1 GB and docs/media had grown to 10 GB, so deploys hung. Now:
- every rendered post image and clip is uploaded as an asset of one of the releases media-0 .. media-7
  (the bucket is the sum of the character codes of the asset name, modulo 8; the dashboard uses the same rule);
- only small, shared files stay on the site (PINNED) plus the media of posts that go out within STAGE_HOURS,
  because Instagram and Facebook fetch the media from a normal web address.

    python -m lc.mediastore sync      # in workflows, before saving: stage what is due, offload the rest
    python -m lc.mediastore migrate   # once: move everything that is in git now (works in a blobless checkout)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
REPO = os.environ.get("GITHUB_REPOSITORY", "sttpjoshua/sidewayswire")
PINNED = ("docs/media/portraits/", "docs/media/stills/", "docs/media/photos/", "docs/media/thumbs/", "docs/media/.gitkeep")
STAGE_HOURS = 36
BUCKETS = 8
API = "https://api.github.com"


def asset_name(path: str) -> str:
    return path.removeprefix("docs/").removeprefix("media/").replace("/", "__")


def tag_for(path: str) -> str:
    return f"media-{sum(map(ord, asset_name(path))) % BUCKETS}"


def url(path: str) -> str:
    """Public address of a media file. Pinned files stay on the site, the rest is in a release."""
    p = path if path.startswith("docs/") else "docs/" + path
    if p.startswith(PINNED):
        return p.removeprefix("docs/")
    return f"https://github.com/{REPO}/releases/download/{tag_for(p)}/{asset_name(p)}"


def is_pinned(path: str) -> bool:
    return path.startswith(PINNED)


# ---------- GitHub releases ----------
def _h() -> dict:
    t = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not t:
        raise RuntimeError("GH_TOKEN ontbreekt")
    return {"Authorization": f"Bearer {t}", "Accept": "application/vnd.github+json"}


@lru_cache(maxsize=None)
def _release(tag: str) -> dict:
    r = requests.get(f"{API}/repos/{REPO}/releases/tags/{tag}", headers=_h(), timeout=30)
    if r.status_code == 404:
        r = requests.post(f"{API}/repos/{REPO}/releases", headers=_h(), timeout=30,
                          json={"tag_name": tag, "name": tag, "make_latest": "false",
                                "body": "Opslag voor media van Sideways Wire (niet op de website)."})
    r.raise_for_status()
    return r.json()


@lru_cache(maxsize=None)
def _assets(tag: str) -> dict:
    rel, out, page = _release(tag), {}, 1
    while True:
        r = requests.get(f"{API}/repos/{REPO}/releases/{rel['id']}/assets", headers=_h(),
                         params={"per_page": 100, "page": page}, timeout=30)
        r.raise_for_status()
        for a in r.json():
            out[a["name"]] = a
        if len(r.json()) < 100:
            return out
        page += 1


def upload(path: str, data_file: Path) -> None:
    """Upload (or replace when the size changed) one file as a release asset."""
    tag, name = tag_for(path), asset_name(path)
    have, size = _assets(tag).get(name), data_file.stat().st_size
    if have and have["size"] == size:
        return
    if have:
        requests.delete(f"{API}/repos/{REPO}/releases/assets/{have['id']}", headers=_h(), timeout=30)
    ctype = {".mp4": "video/mp4", ".png": "image/png", ".jpg": "image/jpeg"}.get(data_file.suffix, "application/octet-stream")
    with open(data_file, "rb") as f:
        r = requests.post(f"https://uploads.github.com/repos/{REPO}/releases/{_release(tag)['id']}/assets",
                          headers=_h() | {"Content-Type": ctype}, params={"name": name}, data=f, timeout=900)
    r.raise_for_status()
    _assets(tag)[name] = r.json()


def download(path: str, out: Path) -> bool:
    """The repo is private, so release files need the token (the API sends a short-lived link)."""
    r = None
    if os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"):
        a = _assets(tag_for(path)).get(asset_name(path))
        if a:
            r = requests.get(f"{API}/repos/{REPO}/releases/assets/{a['id']}", stream=True, timeout=300,
                             headers=_h() | {"Accept": "application/octet-stream"})
    if r is None:
        r = requests.get(url(path), stream=True, timeout=300)
    if not r.ok:
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        for c in r.iter_content(1 << 20):
            f.write(c)
    return True


# ---------- which files belong on the site ----------
def due_paths(now: datetime | None = None) -> set[str]:
    """Media of posts that go out within STAGE_HOURS (they must be reachable on the site for Meta)."""
    from . import queue as q
    now, keep = now or datetime.now(timezone.utc), set()
    for p in q.load():
        if p.get("status") not in ("ready", "approved"):
            continue
        times = [t for pl, t in (p.get("plan") or {}).items() if pl not in (p.get("results") or {})]
        times = times or ([p["post_at"]] if p.get("post_at") else [])
        if times and min(datetime.fromisoformat(t) for t in times) - now <= timedelta(hours=STAGE_HOURS):
            files = list(p.get("media") or []) + ([p["short"]] if p.get("short") else [])
            keep.update(m for m in files if m.startswith("docs/media/"))
    return keep


def sync() -> dict:
    """Stage the media that is due, offload everything else that is in docs/media."""
    keep, rep = due_paths(), {"staged": 0, "offloaded": 0, "errors": []}
    for p in sorted(keep):
        f = ROOT / p
        if not f.exists():
            if download(p, f):
                rep["staged"] += 1
            else:
                rep["errors"].append(f"stage {p}")
    for f in sorted(MEDIA.rglob("*")):
        if not f.is_file():
            continue
        p = str(f.relative_to(ROOT))
        if is_pinned(p) or p in keep:
            continue
        try:
            upload(p, f)
            f.unlink()
            rep["offloaded"] += 1
        except Exception as e:
            rep["errors"].append(f"{p}: {str(e)[:120]}")
    for d in sorted(MEDIA.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return rep


def migrate() -> dict:
    """Move every tracked media file to the releases without needing it on disk (blobless clone)."""
    keep = due_paths()
    ls = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD", "docs/media"], cwd=ROOT,
                        capture_output=True, text=True, check=True).stdout.split()
    todo = [p for p in ls if not is_pinned(p) and p not in keep]
    rep = {"moved": 0, "errors": []}
    with tempfile.TemporaryDirectory() as tmp:
        for i, p in enumerate(todo, 1):
            f = Path(tmp) / "blob"
            try:
                with open(f, "wb") as out:
                    subprocess.run(["git", "cat-file", "blob", f"HEAD:{p}"], cwd=ROOT, stdout=out, check=True)
                f = f.rename(Path(tmp) / ("x" + Path(p).suffix))
                upload(p, f)
                subprocess.run(["git", "update-index", "--force-remove", p], cwd=ROOT, check=True)
                rep["moved"] += 1
            except Exception as e:
                rep["errors"].append(f"{p}: {str(e)[:120]}")
            finally:
                for x in Path(tmp).iterdir():
                    x.unlink()
            if i % 50 == 0:
                print(f"{i}/{len(todo)}", flush=True)
    return rep


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    print(json.dumps(migrate() if cmd == "migrate" else sync(), indent=1)[:4000])

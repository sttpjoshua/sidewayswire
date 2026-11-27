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


PUBLIC_REPO = "sttpjoshua/sidewayswire-media"     # public: dashboard on any device, Meta/TikTok can fetch


def public() -> bool:
    """True once the media has moved to the public repo (data/settings.json "media_public")."""
    try:
        return bool(json.loads((ROOT / "data" / "settings.json").read_text()).get("media_public"))
    except Exception:
        return False


def url(path: str) -> str:
    """Public address of a media file. Pinned files stay on the site, the rest is in a release."""
    p = path if path.startswith("docs/") else "docs/" + path
    if p.startswith(PINNED):
        return p.removeprefix("docs/")
    repo = PUBLIC_REPO if public() else REPO
    return f"https://github.com/{repo}/releases/download/{tag_for(p)}/{asset_name(p)}"


def is_pinned(path: str) -> bool:
    return path.startswith(PINNED)


# ---------- GitHub releases (repo is the private main repo or the public media repo) ----------
def _token(repo: str) -> str:
    t = os.environ.get("MEDIA_TOKEN") if repo == PUBLIC_REPO else (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    if not t:
        raise RuntimeError(f"sleutel voor {repo} ontbreekt")
    return t


def _h(repo: str = REPO) -> dict:
    return {"Authorization": f"Bearer {_token(repo)}", "Accept": "application/vnd.github+json"}


def target() -> str:
    """Where new files go: the public repo as soon as its key (MEDIA_TOKEN) is there."""
    return PUBLIC_REPO if os.environ.get("MEDIA_TOKEN") else REPO


@lru_cache(maxsize=None)
def _release(tag: str, repo: str = REPO) -> dict:
    r = requests.get(f"{API}/repos/{repo}/releases/tags/{tag}", headers=_h(repo), timeout=30)
    if r.status_code == 404:
        r = requests.post(f"{API}/repos/{repo}/releases", headers=_h(repo), timeout=30,
                          json={"tag_name": tag, "name": tag, "make_latest": "false",
                                "body": "Media van Sideways Wire (clips en posts)."})
    r.raise_for_status()
    return r.json()


@lru_cache(maxsize=None)
def _assets(tag: str, repo: str = REPO) -> dict:
    rel, out, page = _release(tag, repo), {}, 1
    while True:
        r = requests.get(f"{API}/repos/{repo}/releases/{rel['id']}/assets", headers=_h(repo),
                         params={"per_page": 100, "page": page}, timeout=30)
        r.raise_for_status()
        for a in r.json():
            out[a["name"]] = a
        if len(r.json()) < 100:
            return out
        page += 1


def upload(path: str, data_file: Path, repo: str | None = None) -> None:
    """Upload (or replace when the size changed) one file as a release asset."""
    repo = repo or target()
    tag, name = tag_for(path), asset_name(path)
    have, size = _assets(tag, repo).get(name), data_file.stat().st_size
    if have and have["size"] == size:
        return
    if have:
        requests.delete(f"{API}/repos/{repo}/releases/assets/{have['id']}", headers=_h(repo), timeout=30)
    ctype = {".mp4": "video/mp4", ".png": "image/png", ".jpg": "image/jpeg"}.get(data_file.suffix, "application/octet-stream")
    with open(data_file, "rb") as f:
        r = requests.post(f"https://uploads.github.com/repos/{repo}/releases/{_release(tag, repo)['id']}/assets",
                          headers=_h(repo) | {"Content-Type": ctype}, params={"name": name}, data=f, timeout=900)
    r.raise_for_status()
    _assets(tag, repo)[name] = r.json()


def _get(path: str, repo: str):
    if repo == PUBLIC_REPO:
        return requests.get(f"https://github.com/{repo}/releases/download/{tag_for(path)}/{asset_name(path)}",
                            stream=True, timeout=300)
    a = _assets(tag_for(path), repo).get(asset_name(path))     # private repo: via the API with the key
    if not a:
        return None
    return requests.get(f"{API}/repos/{repo}/releases/assets/{a['id']}", stream=True, timeout=300,
                        headers=_h(repo) | {"Accept": "application/octet-stream"})


def download(path: str, out: Path) -> bool:
    for repo in (PUBLIC_REPO, REPO):
        try:
            r = _get(path, repo)
        except Exception:
            r = None
        if r is not None and r.ok:
            out.parent.mkdir(parents=True, exist_ok=True)
            with open(out, "wb") as f:
                for c in r.iter_content(1 << 20):
                    f.write(c)
            return True
    return False


def to_public() -> dict:
    """Copy every asset of the private media releases to the public repo, then switch the addresses."""
    rep = {"copied": 0, "had": 0, "errors": []}
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(BUCKETS):
            tag = f"media-{i}"
            have = _assets(tag, PUBLIC_REPO)
            for name, a in _assets(tag, REPO).items():
                if name in have and have[name]["size"] == a["size"]:
                    rep["had"] += 1
                    continue
                f = Path(tmp) / ("x" + Path(name).suffix)
                try:
                    r = requests.get(f"{API}/repos/{REPO}/releases/assets/{a['id']}", stream=True, timeout=300,
                                     headers=_h(REPO) | {"Accept": "application/octet-stream"})
                    r.raise_for_status()
                    with open(f, "wb") as out:
                        for c in r.iter_content(1 << 20):
                            out.write(c)
                    upload("docs/media/" + name.replace("__", "/"), f, PUBLIC_REPO)
                    rep["copied"] += 1
                except Exception as e:
                    rep["errors"].append(f"{name}: {str(e)[:100]}")
                f.unlink(missing_ok=True)
            print(tag, rep["copied"], flush=True)
    if not rep["errors"]:
        st = ROOT / "data" / "settings.json"
        d = json.loads(st.read_text())
        d["media_public"] = True
        st.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    return rep


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
            files = list(p.get("media") or []) + [p[k] for k in ("short", "long") if p.get(k)]
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
    run = {"migrate": migrate, "public": to_public}.get(cmd, sync)
    print(json.dumps(run(), indent=1)[:4000])

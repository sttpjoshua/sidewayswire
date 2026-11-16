#!/usr/bin/env python3
"""Sideways Wire video helper, runs on Joshua's Mac every 15 minutes (launchd).

YouTube blocks downloads from GitHub's servers, but not from a normal connection.
This helper:
  1. looks for podcast clip moments from episodes that are on YouTube and still have no video,
  2. finds where the moment sits in the YouTube video (by matching YouTube's captions to our transcript,
     because the video and the podcast audio often do not start at the same point),
  3. downloads only that part with yt-dlp,
  4. uploads it to the GitHub release "video-sources" and starts the podcasts workflow,
     which then makes the clip again, now with video.
It also writes a heartbeat in the release text, so the dashboard shows that the Mac is alive.

Only the Python standard library, yt-dlp and ffmpeg are used. The GitHub key is read from the macOS
keychain (service "sidewayswire-mac"); it is never written to a file.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

REPO = "sttpjoshua/sidewayswire"
API = f"https://api.github.com/repos/{REPO}"
TAG = "video-sources"
VERSION = "2"
HOME = Path.home()
STATE = HOME / "Library" / "Application Support" / "SidewaysWire" / "state.json"
CACHE = HOME / "Library" / "Caches" / "SidewaysWire"
PATH_EXTRA = ["/opt/homebrew/bin", "/usr/local/bin"]
os.environ["PATH"] = ":".join(PATH_EXTRA + [os.environ.get("PATH", "/usr/bin:/bin")])


def log(*a):
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def token() -> str:
    return subprocess.run(["security", "find-generic-password", "-s", "sidewayswire-mac", "-w"],
                          capture_output=True, text=True, check=True).stdout.strip()


KEY = None


def gh(path: str, method="GET", body=None, raw=False, url=None, data=None, ctype=None):
    req = urllib.request.Request(url or API + path, method=method,
                                 data=data if data is not None else (json.dumps(body).encode() if body is not None else None))
    req.add_header("Authorization", f"Bearer {KEY}")
    req.add_header("Accept", "application/vnd.github.raw" if raw else "application/vnd.github+json")
    if ctype or body is not None:
        req.add_header("Content-Type", ctype or "application/json")
    with urllib.request.urlopen(req, timeout=300) as r:
        out = r.read()
        return out if raw else (json.loads(out) if out else None)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"failed": {}}


def save_state(s: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1))


def release() -> dict:
    try:
        return gh(f"/releases/tags/{TAG}")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    return gh("/releases", "POST", {"tag_name": TAG, "target_commitish": "main", "name": "Video sources (Mac helper)",
                                    "body": "{}", "prerelease": True})


# ---------- captions and alignment ----------
_norm_re = re.compile(r"[^a-z0-9 ]+")


def norm(w: str) -> str:
    return _norm_re.sub("", w.lower()).strip()


def captions(youtube_id: str) -> list[tuple[float, str]]:
    """Word-level (time, word) from YouTube's automatic English captions, cached per video."""
    CACHE.mkdir(parents=True, exist_ok=True)
    vtts = list(CACHE.glob(f"{youtube_id}*.vtt"))
    if not vtts:
        r = subprocess.run(["yt-dlp", "--no-warnings", "--skip-download", "--write-auto-subs", "--write-subs",
                            "--sub-langs", "en.*,en,-live_chat", "--sub-format", "vtt/best", "-o", str(CACHE / youtube_id),
                            f"https://www.youtube.com/watch?v={youtube_id}"], capture_output=True, text=True, timeout=300)
        vtts = list(CACHE.glob(f"{youtube_id}*.vtt"))
        if not vtts:
            log(f"yt-dlp ondertitels {youtube_id} (code {r.returncode}):", (r.stderr or r.stdout)[-600:].replace("\n", " | "))
    if not vtts:
        return []
    words, seen = [], set()
    ts = lambda h, m, s: int(h) * 3600 + int(m) * 60 + float(s)
    for block in vtts[0].read_text(errors="ignore").split("\n\n"):
        m = re.search(r"(\d+):(\d+):([\d.]+) --> ", block)
        if not m:
            continue
        t0 = ts(*m.groups())
        for line in block.splitlines()[1:]:
            if "-->" in line or not line.strip():
                continue
            if "<" in line:   # word timings: word<00:00:01.234><c> next</c>
                parts = re.split(r"<(\d+):(\d+):([\d.]+)>", line)
                t = t0
                w = re.sub(r"<[^>]+>", "", parts[0])
                chunks = [(t, w)]
                for i in range(1, len(parts) - 3, 4):
                    chunks.append((ts(parts[i], parts[i + 1], parts[i + 2]), re.sub(r"<[^>]+>", "", parts[i + 3])))
                for t, text in chunks:
                    for w in text.split():
                        key = (round(t, 2), w)
                        if key not in seen:
                            seen.add(key)
                            words.append((t, norm(w)))
    if not words:      # plain captions without word timings: spread the words over each cue
        for block in vtts[0].read_text(errors="ignore").split("\n\n"):
            m = re.search(r"(\d+):(\d+):([\d.]+) --> (\d+):(\d+):([\d.]+)", block)
            if not m:
                continue
            a, b = ts(*m.groups()[:3]), ts(*m.groups()[3:])
            ws = " ".join(l for l in block.splitlines() if "-->" not in l and not l.strip().isdigit()).split()
            for k, w in enumerate(ws):
                words.append((a + (b - a) * k / max(len(ws), 1), norm(w)))
    return [(t, w) for t, w in words if w]


def offset_at(ours: list[tuple[float, str]], theirs: list[tuple[float, str]], at: float) -> float | None:
    """Seconds to add to our time `at` to get the YouTube time, from ~40 words around `at`."""
    near = [x for x in ours if at - 20 <= x[0] <= at + 25][:60]
    if len(near) < 12:
        return None
    a, b = [w for _, w in near], [w for _, w in theirs]
    sm = SequenceMatcher(None, a, b, autojunk=False)
    # coarse search: best window in their words
    best, best_i = 0.0, None
    step = 20
    for i in range(0, max(len(b) - len(a), 1), step):
        r = SequenceMatcher(None, a, b[i:i + len(a) + 40], autojunk=False).ratio()
        if r > best:
            best, best_i = r, i
    if best_i is None or best < 0.35:
        return None
    lo = max(best_i - 40, 0)
    sm = SequenceMatcher(None, a, b[lo:lo + len(a) + 120], autojunk=False)
    diffs = []
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            diffs.append(theirs[lo + blk.b + k][0] - near[blk.a + k][0])
    if len(diffs) < 8:
        return None
    diffs.sort()
    return diffs[len(diffs) // 2]


def our_words(transcript: dict) -> list[tuple[float, str]]:
    out = []
    for s in transcript["segments"]:
        for w in s.get("words") or []:
            n = norm(w[2])
            if n:
                out.append((w[0], n))
    return out


# ---------- main ----------
def asset_name(ep_id: str, i: int, m: dict) -> str:
    return f"{ep_id}-{i}-{int(round(m['start'] * 10))}-{int(round(m['end'] * 10))}.mp4"


def download(youtube_id: str, a: float, b: float, out: Path) -> bool:
    r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b",
                        "--merge-output-format", "mp4", "--download-sections", f"*{a:.2f}-{b:.2f}",
                        "--force-keyframes-at-cuts", "-o", str(out), f"https://www.youtube.com/watch?v={youtube_id}"],
                       capture_output=True, text=True, timeout=900)
    if r.returncode:
        log("yt-dlp:", r.stderr[-400:])
    return out.exists() and out.stat().st_size > 100_000


def daily_update(state: dict):
    if time.time() - state.get("updated_ytdlp", 0) < 86400 or not shutil.which("brew"):
        return
    subprocess.run(["brew", "upgrade", "-q", "yt-dlp"], capture_output=True, timeout=900)
    state["updated_ytdlp"] = time.time()
    log("yt-dlp bijgewerkt")


def main():
    global KEY
    KEY = token()
    state = load_state()
    daily_update(state)
    rel = release()
    have = {a["name"] for a in rel.get("assets", [])}
    ix = json.loads(gh("/contents/data/podcasts/episodes.json?ref=main", raw=True))
    uploaded, errors, waiting = [], [], 0
    for ep in ix["episodes"].values():
        if not ep.get("youtube"):
            continue
        try:
            moments = json.loads(gh(f"/contents/data/podcasts/moments/{ep['id']}.json?ref=main", raw=True))
        except urllib.error.HTTPError:
            continue
        todo = [(i, m) for i, m in enumerate(moments)
                if m.get("status") in ("new", "queued") and m.get("mode") != "video"
                and asset_name(ep["id"], i, m) not in have]
        if not todo:
            continue
        theirs, ours = None, None
        for i, m in todo:
            name = asset_name(ep["id"], i, m)
            if time.time() - state["failed"].get(name, 0) < 3600:
                continue                               # failed recently, try again later
            waiting += 1
            try:
                if theirs is None:
                    theirs = captions(ep["youtube"])
                    ours = our_words(json.loads(gh(f"/contents/data/podcasts/t/{ep['id']}.json?ref=main", raw=True)))
                if not theirs:
                    raise RuntimeError("geen YouTube-ondertitels om op uit te lijnen")
                o1, o2 = offset_at(ours, theirs, m["start"]), offset_at(ours, theirs, m["end"] - 10)
                if o1 is None and o2 is None:
                    raise RuntimeError("moment niet teruggevonden in de video")
                o1 = o1 if o1 is not None else o2
                o2 = o2 if o2 is not None else o1
                if abs(o1 - o2) > 3:
                    log(f"{name}: begin en eind verschillen {o2 - o1:.1f} s, ik neem het begin")
                a, b = m["start"] + o1, m["start"] + o1 + (m["end"] - m["start"])
                log(f"{name}: verschuiving {o1:+.1f} s, video {a:.1f} tot {b:.1f}")
                with tempfile.TemporaryDirectory() as tmp:
                    f = Path(tmp) / name
                    if not download(ep["youtube"], a, b, f):
                        raise RuntimeError("download mislukt")
                    up = rel["upload_url"].split("{")[0] + "?name=" + name
                    gh("", "POST", url=up, data=f.read_bytes(), ctype="video/mp4")
                uploaded.append(name)
                state["failed"].pop(name, None)
                log("geupload", name)
            except Exception as ex:
                state["failed"][name] = time.time()
                errors.append(f"{name}: {ex}")
                log("fout", name, ex)
    if uploaded:
        gh("/actions/workflows/podcasts.yml/dispatches", "POST", {"ref": "main", "inputs": {"per_run": "0", "episode": ""}})
        log("clips worden opnieuw gemaakt")
    beat = {"seen": datetime.now(timezone.utc).isoformat(), "version": VERSION, "uploaded": uploaded,
            "errors": errors[-5:], "waiting": waiting}
    old = {}
    try:
        old = json.loads(rel.get("body") or "{}")
    except Exception:
        pass
    if uploaded or errors:
        beat["last_upload"] = beat["seen"] if uploaded else old.get("last_upload")
    else:
        beat["last_upload"] = old.get("last_upload")
    gh(f"/releases/{rel['id']}", "PATCH", {"body": json.dumps(beat)})
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        log("gestopt:", ex)
        sys.exit(1)

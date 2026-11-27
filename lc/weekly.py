"""Sideways Weekly (Joshua, 27 nov 2026): every Sunday a video of the 5 biggest stories of the week.

No voice and no photos: only our own typography, animated, so it always counts as own work.
Two versions: vertical 1080x1920 (Reels, TikTok, Shorts) and landscape 1920x1080 (YouTube, Facebook).

How a frame is made: templates/weekly_frame.html has paused entrance animations; for every frame we
seek them (window.__seek) and take a screenshot, then ffmpeg holds the last frame for the rest of
the segment. The music is not added here: the Epidemic Sound tracks may not be in this public repo,
so the Mac helper puts a track under the video (status "music") and hands it back as a draft; from
there it goes to Joshua's check (BEOORDELEN) like every new format.

    python -m lc.weekly             # make this week's video (formats workflow, Sunday morning)
    python -m lc.weekly --nieuw     # make it again
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import queue as q
from .formats import NL, TAGS, _check, _want, week_id

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
STORY_KINDS = ("breaking", "hook", "news", "standings", "results", "result", "champion")
FPS = 30
ANIM_MS = 1300           # all entrance animations are done by then
SERIES = [("D1GP", r"\bD1 ?GP\b"), ("D1NZ", r"\bD1NZ\b"), ("Drift Kings", r"drift kings"),
          ("Drift Masters", r"drift ?masters|\bDMGP\b"), ("Formula DRIFT", r"\bformula ?d(rift)?\b|#formulad|\bFD\b")]


def _clean(text: str) -> str:
    text = re.sub(r"#\w+", "", text or "")
    text = re.sub(r"@\w[\w.]*", "", text)
    text = re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def body_of(caption: str, limit: int = 150) -> str:
    parts = re.findall(r"[^.!?]+[.!?]+", _clean(caption)) or [_clean(caption)]
    out = ""
    for s in parts:
        s = s.strip()
        if out and len(out) + len(s) + 1 > limit:
            break
        out = (out + " " + s).strip()
    return out if len(out) <= limit + 40 else out[:limit].rsplit(" ", 1)[0] + "…"


def split_title(title: str) -> list[str]:
    """Two balanced tape lines."""
    w = title.upper().split()
    if len(" ".join(w)) <= 16 or len(w) < 2:
        return [" ".join(w)]
    best = min(range(1, len(w)), key=lambda i: abs(len(" ".join(w[:i])) - len(" ".join(w[i:]))))
    return [" ".join(w[:best]), " ".join(w[best:])]


def series_of(p: dict) -> str:
    text = " ".join([p.get("series") or "", p.get("title") or "", p.get("caption") or ""])
    for name, pat in SERIES:
        if re.search(pat, text, re.I):
            return name.upper()
    return "DRIFT NEWS"


def stories(now: datetime, n: int = 5) -> list[dict]:
    since = now - timedelta(days=7)
    seen, out = set(), []
    posts = [p for p in q.load() if p.get("kind") in STORY_KINDS and p.get("status") not in ("skipped",)
             and p.get("created") and datetime.fromisoformat(p["created"]) >= since]
    for p in sorted(posts, key=lambda p: -(p.get("urgency") or 0)):
        key = (p.get("story") or p.get("title") or p["id"]).lower()
        title = p.get("title") or (p.get("hook") or {}).get("text") or p.get("story") or ""
        body = body_of(p.get("caption") or "")
        if key in seen or not title or not body:
            continue
        seen.add(key)
        when = datetime.fromisoformat(p["created"]).astimezone(NL)
        out.append({"post": p["id"], "title": title.rstrip("."), "body": body, "series": series_of(p),
                    "when": when.strftime("%a %d %b").upper().replace(" 0", " ")})
        if len(out) == n:
            break
    return out


def seconds_for(seg: dict) -> float:
    if seg["kind"] != "story":
        return 3.5
    return max(7.0, min(13.0, len(seg["body"].split()) / 2.6 + 3.5))


def segments(week: str, st: list[dict]) -> list[dict]:
    n = len(st)
    segs = [{"kind": "intro"}]
    segs += [{"kind": "story", "i": i, **s} for i, s in enumerate(st, 1)]
    segs.append({"kind": "outro"})
    for s in segs:
        s.update(week=week.split("-W")[1].lstrip("0"), n=n)
    return segs


def _frame_data(seg: dict, shape: str) -> dict:
    v = shape == "v"
    d = dict(seg, shape=shape, w=1080 if v else 1920, h=1920 if v else 1080)
    if seg["kind"] == "story":
        size = 120 if v else 88
        lines = split_title(seg["title"])
        d["headline"] = [[t, size, ["darkb", "accent"][k % 2]] for k, t in enumerate(lines)]
    return d


def render(segs: list[dict], out_dir: Path, shapes=("v", "h")) -> dict:
    from .render import Renderer
    out = {}
    tmp = Path(tempfile.mkdtemp(prefix="weekly-"))
    try:
        with Renderer() as r:
            for shape in shapes:
                parts = []
                for k, seg in enumerate(segs):
                    d = _frame_data(seg, shape)
                    page = r._browser.new_page(viewport={"width": d["w"], "height": d["h"]}, device_scale_factor=1)
                    html = tmp / f"{shape}{k}.html"
                    html.write_text(r.html("weekly_frame.html", d), encoding="utf-8")
                    fdir = tmp / f"{shape}{k}"
                    fdir.mkdir()
                    try:
                        page.goto(html.as_uri())
                        page.evaluate("document.fonts.ready")
                        page.evaluate("window.__runFit()")
                        nfr = int(ANIM_MS / 1000 * FPS)
                        for f in range(nfr + 1):
                            page.evaluate(f"window.__seek({f * 1000 / FPS})")
                            page.locator("#frame").screenshot(path=str(fdir / f"{f:03d}.jpg"), type="jpeg", quality=93)
                    finally:
                        page.close()
                    hold = max(0.5, seconds_for(seg) - ANIM_MS / 1000)
                    part = tmp / f"{shape}{k}.mp4"
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", str(fdir / "%03d.jpg"),
                                    "-vf", f"tpad=stop_mode=clone:stop_duration={hold:.2f},format=yuv420p",
                                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-r", str(FPS), str(part)], check=True)
                    parts.append(part)
                lst = tmp / f"{shape}.txt"
                lst.write_text("".join(f"file '{p}'\n" for p in parts))
                dest = out_dir / ("vertical.mp4" if shape == "v" else "horizontal.mp4")
                dest.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                                "-c", "copy", "-movflags", "+faststart", str(dest)], check=True)
                out[shape] = dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def make(now: datetime | None = None, force: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(NL).date()
    wk = week_id(local)
    pid = f"{local.isoformat()}-sideways-weekly"
    if (q.QUEUE / f"{pid}.json").exists() and not force:
        return {"skip": "bestaat al", "id": pid}
    st = stories(now)
    if len(st) < 3:
        return {"skip": f"te weinig verhalen deze week ({len(st)})"}
    segs = segments(wk, st)
    files = render(segs, MEDIA / pid)
    rel = {k: str(v.relative_to(ROOT)) for k, v in files.items()}
    n = wk.split("-W")[1].lstrip("0")
    lines = "\n".join(f"{i}. {s['title'].title()}" for i, s in enumerate(st, 1))
    post = {"id": pid, "kind": "weekly", "own_format": "weekly", "story": f"Sideways Weekly week {n}",
            "title": f"SIDEWAYS WEEKLY · WEEK {n}", "slides": [], "video": rel["v"], "long": rel["h"],
            "caption": f"Sideways Weekly, week {n}: the {len(st)} drift stories you need to know 🔥\n\n{lines}\n\n"
                       f"Which one was the biggest for you?\n\n{TAGS}",
            "platforms": ["instagram", "facebook", "tiktok", "youtube"], "format": "reel",
            "people": [], "stories": [s["post"] for s in st], "week": wk,
            "check": _check("weekly"), "check_reason": "nieuw format Sideways Weekly: kijk hem even terug",
            "status": "music", "music_wait": "de Mac zet er een Epidemic Sound-track onder",
            "created": now.isoformat(), "by": "weekly", "want_at": _want(local, "10:00"),
            "seconds": round(sum(seconds_for(s) for s in segs), 1)}
    q.save(post)
    return {"made": pid, "seconds": post["seconds"], "stories": [s["title"] for s in st]}


if __name__ == "__main__":
    print(json.dumps(make(force="--nieuw" in sys.argv), indent=1, ensure_ascii=False))

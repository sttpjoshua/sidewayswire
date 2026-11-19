"""Short versions (max SHORT_MAX s) of the clips for TikTok and YouTube Shorts.

A clip opens with its hook (the strongest line), flashes back and then plays the whole moment, often
45 to 60 seconds. On TikTok and Shorts completion decides the reach, so the short version keeps the
hook and then plays the part of the moment that leads up to that line and ends just after it: build-up
and payoff in under 30 seconds. Clips without a hook keep their first 30 seconds. Split battles
(lead vs lead, chase vs chase) are not cut: they only make sense whole.

    python -m lc.shorts [max]     # makes up to max short versions, planned posts first
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import mediastore, planner
from . import queue as q

ROOT = Path(__file__).resolve().parent.parent
SHORT_MAX = 30.0
FADE = 0.35          # same crossfade as clips.make_clip
PAYOFF = 2.5         # seconds kept after the hook line


def _dur(f: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                         capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def windows(m: dict, clip_len: float) -> list[tuple[float, float]] | None:
    """Parts of the clip file to keep, or None when the clip is short enough already."""
    if clip_len <= SHORT_MAX + 2:
        return None
    hook = m.get("hook") or {}
    try:
        start, end = float(m["start"]), float(m["end"])
        hs, he = float(hook["start"]), float(hook["end"])
        ok = not hook.get("off") and start <= hs < he <= end and 1.0 <= he - hs <= 6.0
    except (KeyError, TypeError, ValueError):
        ok = False
    if not ok:
        return [(0.0, SHORT_MAX)]
    hl = he - hs
    main0 = hl - FADE                                  # where the moment starts in the clip file
    length = SHORT_MAX - hl
    m_end = min(he - start + PAYOFF, end - start)
    m_start = max(0.0, m_end - length)
    if m_start < 0.5:                                  # the moment is short: just play on from the hook
        return [(0.0, min(clip_len, main0 + m_end))]
    return [(0.0, main0), (main0 + m_start, min(clip_len, main0 + m_end))]


def cut(src: Path, parts: list[tuple[float, float]], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if len(parts) == 1:
        a, b = parts[0]
        flt = (f"[0:v]trim={a}:{b},setpts=PTS-STARTPTS,fade=t=out:st={b - a - 0.4:.2f}:d=0.4[v];"
               f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,afade=t=out:st={b - a - 0.4:.2f}:d=0.4[a]")
    else:
        (a1, b1), (a2, b2) = parts
        d1, d2 = b1 - a1, b2 - a2
        flt = (f"[0:v]trim={a1}:{b1},setpts=PTS-STARTPTS[v1];[0:v]trim={a2}:{b2},setpts=PTS-STARTPTS[v2];"
               f"[0:a]atrim={a1}:{b1},asetpts=PTS-STARTPTS[a1];[0:a]atrim={a2}:{b2},asetpts=PTS-STARTPTS[a2];"
               f"[v1][v2]xfade=transition=fadewhite:duration={FADE}:offset={d1 - FADE:.2f},"
               f"fade=t=out:st={d1 + d2 - FADE - 0.4:.2f}:d=0.4,format=yuv420p[v];"
               f"[a1][a2]acrossfade=d={FADE},afade=t=out:st={d1 + d2 - FADE - 0.4:.2f}:d=0.4[a]")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", flt, "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
                    "-movflags", "+faststart", str(out)], check=True)


def thumb(src: Path, pid: str) -> str:
    """Small still for the dashboard lists (on the site itself, so lists load fast)."""
    out = ROOT / "docs" / "media" / "thumbs" / f"{pid}.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "2.5", "-i", str(src), "-frames:v", "1",
                    "-vf", "scale=270:-2", "-q:v", "6", str(out)], check=True)
    return str(out.relative_to(ROOT))


def run(limit: int = 400) -> dict:
    rep = {"made": 0, "not_needed": 0, "split": 0, "errors": []}
    posts = [p for p in q.load() if p.get("status") in ("ready", "approved", "check", "draft")
             and p.get("kind") in ("stream_clip", "podcast_clip", "vlog_clip") and p.get("video")
             and (not p.get("thumb") or not (p.get("short") or p.get("short_none")))]
    posts.sort(key=lambda p: (p.get("post_at") is None, p.get("post_at") or "", -(p.get("score") or 0)))
    with tempfile.TemporaryDirectory() as tmp:
        for p in posts[:limit]:
            try:
                src = ROOT / p["video"]
                if not src.exists():
                    src = Path(tmp) / "src.mp4"
                    if not mediastore.download(p["video"], src):
                        raise RuntimeError("clip niet gevonden")
                if not p.get("thumb"):
                    p["thumb"] = thumb(src, p["id"])
                    rep["thumbs"] = rep.get("thumbs", 0) + 1
                if p.get("short") or p.get("short_none"):
                    q.save(p)
                    continue
                if p.get("format") == "split":
                    p["short_none"] = "split"
                    rep["split"] += 1
                    q.save(p)
                    continue
                parts = windows(planner.moment_of(p), _dur(src))
                if parts is None:
                    p["short_none"] = "kort genoeg"
                    rep["not_needed"] += 1
                else:
                    out = ROOT / Path(p["video"]).with_name("short.mp4")
                    cut(src, parts, out)
                    p["short"] = str(out.relative_to(ROOT))
                    p["short_len"] = round(_dur(out), 1)
                    rep["made"] += 1
                q.save(p)
            except Exception as e:
                rep["errors"].append(f"{p['id']}: {str(e)[:150]}")
    return rep


if __name__ == "__main__":
    print(json.dumps(run(int(sys.argv[1]) if len(sys.argv) > 1 else 400), indent=1))

"""Podcasts: find new episodes and make transcripts with timestamps.

Runs on GitHub Actions every two hours (workflow 'podcasts').
1. Finds each podcast's RSS feed through the Apple Podcasts search API (cached).
2. Lists episodes from the last MAX_AGE_DAYS that have no transcript yet.
3. Downloads the audio and transcribes it with Whisper (faster-whisper, on CPU).
   Every word gets a start and end time, so clips can be cut to the word.
4. Looks for a video version of the episode on YouTube (same title), so the
   clip maker can use video and only falls back to an audiogram without it.

Files:
  data/podcasts/episodes.json        index of all episodes we know
  data/podcasts/t/<id>.json          transcript: segments with words and times
  data/podcasts/t/<id>.txt           readable transcript with [mm:ss] marks (for the editor)
  data/podcasts/moments/<id>.json    moments the editor picked (see EDITOR.md)
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path

import feedparser
import requests

from . import progress

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "podcasts"
INDEX = DIR / "episodes.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; SidewaysWireBot/1.0)"}

MAX_AGE_DAYS = 60          # only recent episodes are news
PER_RUN = int(os.environ.get("PODCASTS_PER_RUN", "3"))
MODEL = os.environ.get("WHISPER_MODEL", "small.en")

# name, Apple search term, YouTube channel with the video version (or None),
# drift_only: general car podcasts, only episodes that are about drifting
PODCASTS = [
    ("The Outerzone", "The Outerzone Official Podcast of Formula DRIFT", "https://www.youtube.com/@FormulaDRIFT", False),
    ("Drift Games Podcast", "Drift Games Podcast", None, False),
    ("The Goodest Cast", "The Goodest Cast Hangout with the Drift Community", None, False),
    ("The SileightyMania Podcast", "SileightyMania Podcast", "https://www.youtube.com/c/thesileightymaniapodcast", False),
    ("The Creative Drive", "The Creative Drive RACER", None, True),
    ("Behind The Wheel", "Behind The Wheel Podcast Konig", None, True),
]


def _drift_words() -> list[str]:
    words = ["drift", "formula d", "d1gp", "d1 grand prix", "gatebil", "nürburgring"]
    src = ROOT / "data" / "sources.csv"
    if src.exists():
        import csv
        words += [r["Naam"].lower() for r in csv.DictReader(src.open(encoding="utf-8"))
                  if r.get("Type") == "Coureur" and len(r["Naam"]) > 6]
    return words


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers=UA, timeout=60, **kw)
    r.raise_for_status()
    return r


def load_index() -> dict:
    return json.loads(INDEX.read_text()) if INDEX.exists() else {"feeds": {}, "episodes": {}}


def save_index(ix: dict):
    DIR.mkdir(parents=True, exist_ok=True)
    INDEX.write_text(json.dumps(ix, indent=1, ensure_ascii=False))


def find_feed(term: str) -> dict:
    """Apple Podcasts search -> the podcast's own RSS feed."""
    r = _get("https://itunes.apple.com/search", params={"media": "podcast", "term": term, "limit": 5}).json()
    if not r.get("results"):
        raise ValueError(f"not found on Apple Podcasts: {term}")
    best = max(r["results"], key=lambda x: SequenceMatcher(None, term.lower(), x["collectionName"].lower()).ratio())
    return {"feed": best["feedUrl"], "title": best["collectionName"], "art": best.get("artworkUrl600")}


def _yt_videos(channel_url: str, cache: dict) -> list[dict]:
    """Recent videos of a YouTube channel (title, id), through its free feed."""
    if channel_url not in cache:
        html = _get(channel_url).text
        m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', html)
        cache[channel_url] = m.group(1) if m else None
    cid = cache[channel_url]
    if not cid:
        return []
    fp = feedparser.parse(_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}").text)
    return [{"title": e.title, "id": e.yt_videoid} for e in fp.entries]


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", t.lower())


def match_video(title: str, videos: list[dict]) -> str | None:
    best, score = None, 0.0
    for v in videos:
        s = SequenceMatcher(None, _norm(title), _norm(v["title"])).ratio()
        if s > score:
            best, score = v["id"], s
    return best if score >= 0.6 else None


def discover(ix: dict) -> list[str]:
    """Update the episode list. Returns ids of new episodes."""
    new, yt_cache = [], ix.setdefault("yt", {})
    since = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    drift_words = _drift_words()
    for name, term, yt, drift_only in PODCASTS:
        try:
            if name not in ix["feeds"] or ix["feeds"][name].get("error"):
                ix["feeds"][name] = find_feed(term)
            info = ix["feeds"][name]
            fp = feedparser.parse(_get(info["feed"]).content)
            videos = _yt_videos(yt, yt_cache) if yt else []
            info.update(ok=datetime.now(timezone.utc).isoformat(), episodes=len(fp.entries))
            for e in fp.entries:
                audio = next((l["href"] for l in e.get("links", []) if l.get("type", "").startswith("audio")), None)
                if not audio or not e.get("published_parsed"):
                    continue
                pub = datetime.fromtimestamp(time.mktime(e.published_parsed), tz=timezone.utc)
                if pub < since:
                    continue
                eid = hashlib.sha1((e.get("id") or audio).encode()).hexdigest()[:12]
                if eid in ix["episodes"]:
                    continue
                ix["episodes"][eid] = {
                    "id": eid, "podcast": name, "title": e.title, "published": pub.isoformat(),
                    "audio": audio, "link": e.get("link"), "art": info.get("art"),
                    "duration": e.get("itunes_duration"), "summary": re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:1500],
                    "youtube": match_video(e.title, videos), "status": "new",
                }
                text = (e.title + " " + e.get("summary", "")).lower()
                if drift_only and not any(w in text for w in drift_words):
                    ix["episodes"][eid]["status"] = "skipped"    # not about drifting
                new.append(eid)
        except Exception as ex:
            ix["feeds"][name] = ix["feeds"].get(name, {}) | {"error": str(ex)[:200]}
    return new


def vocabulary() -> str:
    """Drift words and driver names, so Whisper writes 'hachiroku' and not 'hot choco'."""
    words = ("Drifting podcast. Formula DRIFT, Drift Masters, D1GP, D1NZ, Drift Kings, Gatebil, Pro, PROSPEC, "
             "tandem, lead, chase, Top 32, Great 8, Final 4, OMT, judges, zones, clipping point, initiation, "
             "hachiroku, AE86, Trueno, Levin, Kouki, Zenki, S13, S14, S15, Silvia, 180SX, JZX100, Chaser, 2JZ, "
             "1JZ, SR20, RB26, LS swap, GT86, GR86, Supra, E46, E92, Mustang RTR, Corolla, Nankang, Kenda, Falken, "
             "Nitto, Toyo, Papadakis, RTR, Feal, Hoonigan.")
    src = ROOT / "data" / "sources.csv"
    if src.exists():
        import csv
        names = [r["Naam"] for r in csv.DictReader(src.open(encoding="utf-8"))
                 if r.get("Type") == "Coureur" and r.get("Prioriteit") == "1"]
        words += " Drivers: " + ", ".join(names) + "."
    return words


def _mmss(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def transcribe(ep: dict, model, on_progress=None) -> dict:
    """Download the audio and transcribe it. Returns the transcript dict."""
    import subprocess

    import numpy as np
    with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
        if on_progress:
            on_progress("download", 0.0, ep.get("seconds"))
        with requests.get(ep["audio"], headers=UA, timeout=120, stream=True) as r:
            r.raise_for_status()
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
        f.flush()
        # Decode with ffmpeg ourselves (16 kHz mono), so Whisper needs no audio library.
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", f.name, "-ac", "1", "-ar", "16000",
                              "-f", "s16le", "-"], capture_output=True, check=True).stdout
        audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        segments, info = model.transcribe(audio, vad_filter=True, word_timestamps=True, beam_size=1,
                                          initial_prompt=vocabulary())
        segs = []
        if on_progress:
            on_progress("transcribe", 0.0, info.duration)
        for s in segments:
            if on_progress:
                on_progress("transcribe", s.end / max(info.duration, 1), info.duration)
            segs.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                         "words": [[round(w.start, 2), round(w.end, 2), w.word.strip()] for w in (s.words or [])]})
    return {"id": ep["id"], "podcast": ep["podcast"], "title": ep["title"], "language": info.language,
            "duration": round(info.duration, 1), "segments": segs}


def write_transcript(t: dict):
    d = DIR / "t"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{t['id']}.json").write_text(json.dumps(t, ensure_ascii=False, separators=(",", ":")))
    lines, last = [f"# {t['podcast']}: {t['title']}", ""], -60.0
    for s in t["segments"]:
        mark = f"[{_mmss(s['start'])}] " if s["start"] - last >= 20 else ""
        if mark:
            last = s["start"]
            lines.append("")
        lines.append(mark + s["text"])
    (d / f"{t['id']}.txt").write_text("\n".join(lines).replace("\n\n\n", "\n\n"), encoding="utf-8")


def run() -> dict:
    ix = load_index()
    progress.update(force=True, phase="search", episode=None, todo=[], pct=None)
    new = discover(ix)
    save_index(ix)
    # skipped episodes may become relevant after a source list update
    words = _drift_words()
    for e in ix["episodes"].values():
        if e["status"] == "skipped" and any(w in (e["title"] + " " + e.get("summary", "")).lower() for w in words):
            e["status"] = "new"
    forced = os.environ.get("EPISODE", "").strip()
    if forced and forced in ix["episodes"]:
        ix["episodes"][forced].update(status="new", tries=0)    # asked for on the dashboard
    rank = {p[0]: i for i, p in enumerate(PODCASTS)}
    todo = sorted((e for e in ix["episodes"].values() if e["status"] in ("new", "error") and e.get("tries", 0) < 3),
                  key=lambda e: (e["id"] == forced, e["published"][:10], -rank.get(e["podcast"], 9)),
                  reverse=True)[:max(PER_RUN, 1 if forced else 0)]
    report = {"new_episodes": len(new), "transcribed": [], "errors": []}
    if todo:
        from faster_whisper import WhisperModel
        progress.update(force=True, phase="model", todo=[e["id"] for e in todo],
                        titles={e["id"]: e["title"] for e in todo})
        model = WhisperModel(MODEL, device="cpu", compute_type="int8")
        for n, ep in enumerate(todo):
            t0 = time.time()
            progress.update(force=True, phase="download", episode=ep["id"], title=ep["title"],
                            podcast=ep["podcast"], index=n, pct=0.0, episode_started=datetime.now(timezone.utc).isoformat())

            def tell(phase, pct, duration, _first=[True]):
                first = _first[0] and phase == "transcribe"
                _first[0] = _first[0] and not first
                progress.update(force=first, phase=phase, pct=round(pct, 3), duration=duration,
                                **({"transcribe_started": datetime.now(timezone.utc).isoformat()} if first else {}))
            try:
                t = transcribe(ep, model, tell)
                write_transcript(t)
                ep.update(status="transcribed", transcribed=datetime.now(timezone.utc).isoformat(),
                          words=sum(len(s["words"]) for s in t["segments"]), seconds=t["duration"])
                report["transcribed"].append(f"{ep['podcast']}: {ep['title']} ({int(time.time() - t0)} s)")
            except Exception as ex:
                ep.update(status="error", error=str(ex)[:200], tries=ep.get("tries", 0) + 1)
                report["errors"].append(f"{ep['podcast']}: {ex}")
            save_index(ix)          # keep progress even if a later episode fails
            progress.update(force=True, phase="saved", episode=ep["id"], pct=1.0,
                            finished=(progress._state.get("finished") or []) + [ep["id"]])
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))
    sys.exit(0)

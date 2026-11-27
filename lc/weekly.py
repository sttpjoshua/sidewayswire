"""Eigen formats (Joshua, 27 nov 2026): het weekoverzicht met zijn stem, en de wekelijkse ranglijst.

Weekoverzicht
  script   elke zondag: een script voor de week, in stukjes (intro, de verhalen van de week, de meest
           besproken rijders, afsluiter), in data/weekly/<week>.json. Joshua past de tekst aan in het
           dashboard (WEEKOVERZICHT) en spreekt elk stukje in; de opnames komen in data/weekly/<week>/<id>.<ext>.
  render   maakt per stukje een dia (eigen vormgeving, met het eigen beeld van de post) en zet die onder zijn
           stem, met ondertitels: een staande versie (reels, TikTok, Shorts) en een liggende (YouTube, Facebook).
           Het resultaat komt als post "weekly" in de wachtrij, ter controle bij Joshua. Alles eigen werk.

Ranglijst
  ranking  elke zondag: de meest besproken rijders van de week (in hoeveel nieuwsverhalen ze voorkwamen,
           uit de nieuwsscout), met stijgers en dalers t.o.v. vorige week. Een kop-post in de wachtrij.

    python -m lc.weekly script [--nieuw]      python -m lc.weekly render [week]      python -m lc.weekly ranking
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import queue as q

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "weekly"
MEDIA = ROOT / "docs" / "media"
STORY_KINDS = ("breaking", "hook", "news", "standings", "results", "ranking")
AUDIO_EXT = (".webm", ".m4a", ".mp4", ".mp3", ".wav", ".ogg")


def week_id(now: datetime | None = None) -> str:
    y, w, _ = (now or datetime.now(timezone.utc)).isocalendar()
    return f"{y}-W{w:02d}"


def _clean(text: str) -> str:
    text = re.sub(r"#\w+", "", text or "")
    text = re.sub(r"@\w[\w.]*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _first_sentence(text: str, n: int = 1) -> str:
    t = _clean(text)
    parts = re.findall(r"[^.!?]+[.!?]+", t) or [t]
    return " ".join(x.strip() for x in parts[:n])[:300]


def _sentence_case(title: str) -> str:
    t = title.strip().rstrip("?!.")
    return t[:1].upper() + t[1:].lower() if t.isupper() else t


# ---------------------------------------------------------------- ranglijst
def _drivers() -> list[tuple[str, list[str]]]:
    import csv
    out = []
    for r in csv.DictReader(open(ROOT / "data" / "sources.csv", encoding="utf-8")):
        if not r.get("Nr", "").strip():
            continue
        names = [r["Naam"]] + [a.strip() for a in re.split(r"[;,]", r.get("Aliassen", "")) if a.strip()]
        out.append((r["Naam"], names))
    return out


def buzz(days: int = 7, now: datetime | None = None) -> list[tuple[str, int]]:
    """How many news items of the last days mention each driver (full name or alias)."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    con = sqlite3.connect(ROOT / "data" / "lc.db")
    rows = con.execute("select title, story from items where published >= ?", (since,)).fetchall()
    con.close()
    count = {}
    for name, names in _drivers():
        pats = [re.compile(r"\b" + re.escape(n) + r"\b", re.I) for n in names if len(n) > 3]
        stories = {s or t for t, s in rows if any(p.search(t or "") for p in pats)}
        if stories:
            count[name] = len(stories)
    return sorted(count.items(), key=lambda x: (-x[1], x[0]))


def ranking(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    wk = week_id(now)
    pid = f"{now.date().isoformat()}-ranking-{wk.lower()}"
    if (q.QUEUE / f"{pid}.json").exists():
        return {"skipped": "bestaat al", "id": pid}
    top = buzz(7, now)[:8]
    if len(top) < 5:
        return {"skipped": "te weinig rijders in het nieuws deze week", "n": len(top)}
    last = {}
    lf = DIR / "ranking.json"
    if lf.exists():
        last = json.loads(lf.read_text()).get("positions", {})
    rows = []
    for i, (name, n) in enumerate(top):
        prev = last.get(name)
        move = None if prev is None else ("up" if prev > i else "down" if prev < i else "same")
        rows.append({"name": name.upper(), "points": n, "move": move})
    DIR.mkdir(parents=True, exist_ok=True)
    lf.write_text(json.dumps({"week": wk, "positions": {name: i for i, (name, _) in enumerate(top)}}, indent=1) + "\n")
    leader = top[0][0]
    post = {
        "id": pid, "kind": "ranking", "status": "draft", "by": "weekly", "created": now.isoformat(),
        "title": "MOST TALKED ABOUT DRIVERS", "platforms": ["instagram", "facebook"],
        "people": [n for n, _ in top[:5]],
        "caption": (f"Who had the drift world talking this week? {leader} tops the Sideways Wire buzz ranking, "
                    f"counted from every drift news story of the past 7 days. Who should be on this list next week?\n\n"
                    "#drifting #formuladrift #driftmasters #sidewayswire"),
        "slides": [{"template": "standings.html", "data": {
            "badge": ["WEEK", wk.split("-W")[1]], "title": "MOST TALKED ABOUT", "subtitle": "DRIVERS THIS WEEK",
            "rows": rows, "meta_left": "STORIES IN THE NEWS, LAST 7 DAYS", "meta_right": "@sidewayswire"}}],
    }
    q.save(post)
    return {"made": pid, "top": top[:5]}


# ---------------------------------------------------------------- script
def script(force: bool = False, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    wk = week_id(now)
    f = DIR / f"{wk}.json"
    if f.exists() and not force:
        return {"skipped": "script bestaat al", "week": wk}
    since = now - timedelta(days=7)
    posts = [p for p in q.load() if p.get("kind") in STORY_KINDS and p.get("status") not in ("skipped",)
             and p.get("created") and datetime.fromisoformat(p["created"]) >= since]
    posts.sort(key=lambda p: -(p.get("urgency") or 0))
    n = wk.split("-W")[1].lstrip("0")
    segs = [{"id": "intro", "kind": "intro", "title": f"WEEK {n} IN DRIFT",
             "text": f"This is Sideways Wire Weekly, week {n}. Here is everything that happened in drift this week."}]
    for i, p in enumerate(posts[:5], 1):
        title = p.get("title") or ((p.get("hook") or {}).get("text")) or p.get("story") or ""
        body = _first_sentence(p.get("caption") or "", 2)
        segs.append({"id": f"s{i}", "kind": "story", "title": title.upper()[:60], "post": p["id"],
                     "image": (p.get("media") or [None])[0],
                     "text": body or _sentence_case(title) + "."})
    top = buzz(7, now)[:3]
    if top:
        names = ", ".join(n for n, _ in top[:-1]) + (f" and {top[-1][0]}" if len(top) > 1 else top[0][0])
        segs.append({"id": "buzz", "kind": "ranking", "title": "MOST TALKED ABOUT",
                     "text": f"The most talked-about drivers this week: {names}.", "names": [x for x, _ in top]})
    segs.append({"id": "outro", "kind": "outro", "title": "SEE YOU NEXT WEEK",
                 "text": "That was the week. Follow Sideways Wire for every battle and every story, every week."})
    data = {"week": wk, "made": now.isoformat(), "status": "script", "segments": segs,
            "note": "Pas de tekst aan in het dashboard (WEEKOVERZICHT) en spreek elk stukje in. Engels, rustig tempo."}
    DIR.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return {"made": wk, "segments": len(segs)}


def latest() -> dict | None:
    files = sorted(DIR.glob("20*-W*.json"))
    if not files:
        return None
    d = json.loads(files[-1].read_text())
    rec = DIR / d["week"]
    d["recorded"] = sorted({a.stem for a in rec.glob("*") if a.suffix in AUDIO_EXT}) if rec.exists() else []
    return d


# ---------------------------------------------------------------- render
def _dur(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _srt(text: str, dur: float, out: Path) -> None:
    words = text.split()
    chunks = [" ".join(words[i:i + 6]) for i in range(0, len(words), 6)] or [""]
    total = sum(len(c) for c in chunks) or 1
    t, lines = 0.15, []
    ts = lambda s: f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d},{int(s * 1000 % 1000):03d}"
    for i, c in enumerate(chunks, 1):
        d = max(0.6, (dur - .3) * len(c) / total)
        lines.append(f"{i}\n{ts(t)} --> {ts(min(dur, t + d))}\n{c}\n")
        t += d
    out.write_text("\n".join(lines), encoding="utf-8")


def render(week: str | None = None) -> dict:
    from .render import Renderer
    week = week or (latest() or {}).get("week")
    f = DIR / f"{week}.json"
    if not week or not f.exists():
        return {"error": "geen script"}
    d = json.loads(f.read_text())
    rec = DIR / week
    audio = {a.stem: a for a in rec.glob("*") if a.suffix in AUDIO_EXT} if rec.exists() else {}
    segs = [s for s in d["segments"] if s["id"] in audio]
    if not segs:
        return {"error": "nog niets ingesproken"}
    work = ROOT / ".weekly" / week
    work.mkdir(parents=True, exist_ok=True)
    out_dir = MEDIA / f"weekly-{week.lower()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    n = len(segs)
    results = {}
    with Renderer() as r:
        for shape, (w, h) in {"v": (1080, 1920), "h": (1920, 1080)}.items():
            parts = []
            for i, s in enumerate(segs, 1):
                img = None
                if s.get("image"):
                    src = ROOT / s["image"]
                    if not src.exists():                      # media lives in the releases (lc/mediastore)
                        from . import mediastore
                        try:
                            mediastore.download(s["image"], src)
                        except Exception:
                            pass
                    img = src.as_uri() if src.exists() else None
                png = work / f"{shape}-{s['id']}.png"
                r.render("weekly_slide.html", {"w": w, "h": h, "shape": shape, "title": s["title"], "kind": s["kind"],
                                               "week": week.split("-W")[1].lstrip("0"), "n": i, "of": n, "image": img,
                                               "names": s.get("names") or []}, png)
                a, dur = audio[s["id"]], _dur(audio[s["id"]])
                if dur <= 0:
                    continue
                srt = work / f"{s['id']}.srt"
                _srt(s["text"], dur + .4, srt)
                fs = 15 if shape == "h" else 11
                style = (f"FontName=DejaVu Sans,Bold=1,FontSize={fs},PrimaryColour=&H00FFFFFF,BackColour=&H00111111,"
                         f"BorderStyle=3,Outline=6,Shadow=0,Alignment=2,MarginV={36 if shape == 'h' else 22}")
                part = work / f"{shape}-{i:02d}.mp4"
                vf = (f"scale={w * 2}:{h * 2},zoompan=z='min(zoom+0.0005,1.06)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=30,"
                      f"subtitles={srt}:force_style='{style}',format=yuv420p")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(png), "-i", str(a),
                                "-filter_complex", f"[0:v]{vf}[v];[1:a]apad=pad_dur=0.4,loudnorm=I=-16:TP=-1.5[a]",
                                "-map", "[v]", "-map", "[a]", "-t", f"{dur + .4:.2f}", "-c:v", "libx264", "-preset", "veryfast",
                                "-crf", "21", "-r", "30", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(part)], check=True)
                parts.append(part)
            lst = work / f"{shape}.txt"
            lst.write_text("".join(f"file '{p}'\n" for p in parts))
            out = out_dir / ("vertical.mp4" if shape == "v" else "horizontal.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                            "-movflags", "+faststart", str(out)], check=True)
            results[shape] = str(out.relative_to(ROOT))
    now = datetime.now(timezone.utc)
    pid = f"{now.date().isoformat()}-weekly-{week.lower()}"
    old = q.load(folder=q.QUEUE)
    prev = next((p for p in old if p["id"] == pid), None)
    post = {
        "id": pid, "kind": "weekly", "status": "draft", "by": "weekly", "created": now.isoformat(),
        "title": f"WEEK {week.split('-W')[1].lstrip('0')} IN DRIFT", "video": results.get("v"), "video_long": results.get("h"),
        "platforms": ["instagram", "facebook", "tiktok", "youtube"], "format": "reel",
        "caption": ("Everything that happened in drift this week, in one video. "
                    + " ".join(f"{i}. {s['title'].title()}." for i, s in enumerate([x for x in segs if x["kind"] == "story"], 1))
                    + "\n\n#drifting #formuladrift #driftmasters #sidewayswire"),
        "check": True, "check_reason": "weekoverzicht: kijk hem even terug voor hij online gaat",
    }
    if prev and prev.get("status") in ("ready", "approved", "posted"):
        post["status"] = prev["status"]
    q.save(post)
    d["status"] = "gemaakt"
    d["video"] = results
    d["post"] = pid
    f.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    return {"made": pid, **results}


if __name__ == "__main__":
    a = sys.argv[1:] or ["script"]
    if a[0] == "script":
        print(json.dumps(script(force="--nieuw" in a), ensure_ascii=False))
    elif a[0] == "render":
        print(json.dumps(render(a[1] if len(a) > 1 else None), ensure_ascii=False))
    elif a[0] == "ranking":
        print(json.dumps(ranking(), ensure_ascii=False))

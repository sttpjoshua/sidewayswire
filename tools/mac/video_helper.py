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
VERSION = "12"
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


# ---------- alignment by sound (when YouTube refuses the captions) ----------
SR = 2000          # samples per second used for matching; enough for ~1 ms precision


def _decode(src: str, out: Path) -> Path:
    if not out.exists():
        tmp = out.with_suffix(".part")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-ac", "1", "-ar", str(SR), "-f", "s16le", str(tmp)],
                       check=True, timeout=1800)
        tmp.rename(out)
    return out


def _load(path: Path):
    import numpy as np
    return np.fromfile(path, dtype=np.int16).astype(np.float32)


def youtube_audio(youtube_id: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{youtube_id}.yt.s16"
    if out.exists():
        return out
    src = list(CACHE.glob(f"{youtube_id}.audio.*"))
    if not src:
        r = subprocess.run(["yt-dlp", "--no-warnings", "-f", "ba[ext=m4a]/ba", "-o", str(CACHE / f"{youtube_id}.audio.%(ext)s"),
                            f"https://www.youtube.com/watch?v={youtube_id}"], capture_output=True, text=True, timeout=1800)
        src = [p for p in CACHE.glob(f"{youtube_id}.audio.*") if not p.name.endswith(".part")]
        if not src:
            raise RuntimeError("YouTube-geluid niet op te halen: " + (r.stderr or "")[-300:].replace("\n", " | "))
    _decode(str(src[0]), out)
    for p in src:
        p.unlink(missing_ok=True)       # the small decoded copy is enough
    return out


def podcast_audio(ep: dict) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return _decode(ep["audio"], CACHE / f"{ep['id']}.pod.s16")


def audio_offset(pod, yt, at: float, length: float = 20.0) -> float | None:
    """Seconds to add to podcast time `at` to get the YouTube time, by cross-correlating the sound."""
    import numpy as np
    a = int(at * SR)
    t = pod[a:a + int(length * SR)]
    if len(t) < SR * 5 or len(yt) < len(t):
        return None
    t = t - t.mean()
    tn = float(np.sqrt((t * t).sum()))
    if tn == 0:
        return None
    n = 1 << int(np.ceil(np.log2(len(yt) + len(t))))
    corr = np.fft.irfft(np.fft.rfft(yt, n) * np.conj(np.fft.rfft(t, n)), n)[:len(yt) - len(t) + 1]
    c = np.concatenate([[0.0], np.cumsum(yt.astype(np.float64) ** 2)])
    energy = np.sqrt(np.maximum(c[len(t):] - c[:-len(t)], 1e-9))
    ncc = corr / (energy * tn)
    i = int(np.argmax(ncc))
    peak, rest = ncc[i], np.delete(ncc, slice(max(i - SR, 0), i + SR))
    if peak < 0.3 or peak < rest.mean() + 8 * rest.std():
        return None                     # no clear match
    return i / SR - at


# ---------- the right video ----------
def _ytdlp_lines(args: list[str]) -> list[str]:
    r = subprocess.run(["yt-dlp", "--no-warnings", *args], capture_output=True, text=True, timeout=300)
    return [l for l in r.stdout.splitlines() if l.strip()]


def video_for(ep: dict, state: dict) -> str | None:
    """The YouTube id of the FULL episode. The linked video is sometimes a Short or a highlight:
    then search YouTube for a video with about the same length as the episode."""
    known = state.setdefault("video", {}).get(ep["id"])
    if known and time.time() - known.get("at", 0) < (30 * 86400 if known.get("id") else 86400):
        return known.get("id")
    want = float(ep.get("seconds") or 0)
    pick = None
    if ep.get("youtube"):
        d = _ytdlp_lines(["--print", "%(duration)s", f"https://www.youtube.com/watch?v={ep['youtube']}"])
        dur = float(d[0]) if d and d[0].replace(".", "", 1).isdigit() else 0
        if not want or (dur and 0.85 * want <= dur <= 1.2 * want):
            pick = ep["youtube"]
        else:
            log(f"{ep['id']}: gekoppelde video duurt {dur:.0f} s, aflevering {want:.0f} s; ik zoek de hele aflevering")
    if not pick and want:
        q = f"{ep['podcast']} {ep['title']}"
        best = 0.0
        for line in _ytdlp_lines(["--flat-playlist", "--print", "%(id)s\t%(duration)s\t%(title)s", f"ytsearch10:{q}"]):
            parts = line.split("\t")
            if len(parts) < 3 or not parts[1].replace(".", "", 1).isdigit():
                continue
            vid, dur, title = parts[0], float(parts[1]), parts[2]
            if not 0.85 * want <= dur <= 1.2 * want:
                continue
            score = SequenceMatcher(None, norm(ep["title"]), norm(title)).ratio() + 0.5 * (1 - abs(dur - want) / want)
            if score > best:
                best, pick = score, vid
        log(f"{ep['id']}: " + (f"hele aflevering gevonden: {pick}" if pick else "geen volledige video op YouTube gevonden"))
    state["video"][ep["id"]] = {"id": pick, "at": time.time()}
    return pick


# ---------- livestreams (Formula DRIFT, Drift Masters): find, transcribe on this Mac ----------
VOCAB = ("Formula DRIFT, Drift Masters, tandem, one more time, OMT, lead, chase, proximity, initiation, "
         "Top 32, Top 16, Great 8, Final 4, Deane, Shanahan, Aasbo, Gittin, Forsberg, Field, Hohenstein, Bakchis, "
         "Odi, Brutskiy, Yoshihara, Kakimoto, Wiecek, Barrios, Losada, Dickinson, Beechum, Minowa, Hughes, Kiss, Ruiz")


def _put(path: str, content: bytes, message: str):
    import base64
    sha = None
    try:
        sha = gh(f"/contents/{path}?ref=main").get("sha")
    except urllib.error.HTTPError:
        pass
    body = {"message": message, "branch": "main", "content": base64.b64encode(content).decode()}
    if sha:
        body["sha"] = sha
    gh(f"/contents/{path}", "PUT", body)


def _json_or(path: str, default):
    try:
        return json.loads(gh(f"/contents/{path}?ref=main", raw=True))
    except urllib.error.HTTPError:
        return default


def find_stream(s: dict) -> tuple[str | None, list]:
    """The replay on YouTube: long enough, and the title fits the event."""
    lines = []
    if s.get("channel"):
        lines += _ytdlp_lines(["--flat-playlist", "--playlist-end", "60", "--print",
                               "%(id)s\t%(duration)s\t%(title)s", s["channel"]])
    if s.get("search"):
        lines += _ytdlp_lines(["--flat-playlist", "--print", "%(id)s\t%(duration)s\t%(title)s", f"ytsearch15:{s['search']}"])
    cands, seen = [], set()
    for line in lines:
        p = line.split("\t")
        if len(p) < 3 or p[0] in seen:
            continue
        seen.add(p[0])
        dur = float(p[1]) if p[1].replace(".", "", 1).isdigit() else 0
        if dur < float(s.get("min_hours", 1.5)) * 3600:
            continue
        t = p[2].lower()
        score = sum(2 for w in s.get("words", []) if w in t)
        score += 3 if any(w in t for w in ("top 32", "competition", "final", "battles")) else 0
        score -= 3 if any(w in t for w in ("practice", "qualif", "pro-am", "proam", "prospec", "pro 2")) else 0
        cands.append({"id": p[0], "seconds": dur, "title": p[2], "score": score,
                      "event": any(w in t for w in s.get("words", []))})
    cands.sort(key=lambda c: (c["score"], c["seconds"]), reverse=True)
    fit = [c for c in cands if c["event"]]            # the title must name this event
    best = fit[0]["id"] if fit and fit[0]["score"] > 0 else None
    return best, cands[:8]


def _mmss(x: float) -> str:
    x = int(x)
    return f"{x // 3600}:{x % 3600 // 60:02d}:{x % 60:02d}" if x >= 3600 else f"{x // 60:02d}:{x % 60:02d}"


def mlx():
    try:
        import mlx_whisper
    except ImportError:
        log("mlx-whisper installeren (eenmalig)")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "mlx-whisper"],
                       check=True, timeout=1800)
        import mlx_whisper
    return mlx_whisper


def heard_words(path: Path, t0: float) -> list[tuple[float, str]]:
    """What is actually said in a video piece, with times on the video's own clock (t0 = start of the piece)."""
    res = mlx().transcribe(str(path), path_or_hf_repo="mlx-community/whisper-small.en-mlx", word_timestamps=True,
                           language="en", condition_on_previous_text=False, verbose=None)
    return [(t0 + w["start"], norm(w["word"])) for sg in res.get("segments", []) for w in sg.get("words", [])
            if norm(w.get("word", ""))]


def cut(src: Path, at: float, length: float, out: Path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(src), "-t", f"{length:.3f}",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart", str(out)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("knippen mislukt: " + r.stderr[-300:])


def transcribe_stream(s: dict, yid: str) -> dict:
    """Download the sound of the stream and transcribe it with Whisper for Apple chips."""
    mlx_whisper = mlx()
    CACHE.mkdir(parents=True, exist_ok=True)
    src = [p for p in CACHE.glob(f"{yid}.full.*") if not p.name.endswith(".part")]
    if not src:
        r = subprocess.run(["yt-dlp", "--no-warnings", "-f", "ba[ext=m4a]/ba", "-o", str(CACHE / f"{yid}.full.%(ext)s"),
                            f"https://www.youtube.com/watch?v={yid}"], capture_output=True, text=True, timeout=7200)
        src = [p for p in CACHE.glob(f"{yid}.full.*") if not p.name.endswith(".part")]
        if not src:
            raise RuntimeError("geluid van de stream niet op te halen: " + (r.stderr or "")[-300:])
    log(f"{s['id']}: transcriberen ({src[0].stat().st_size // 1_000_000} MB geluid)")
    res = mlx_whisper.transcribe(str(src[0]), path_or_hf_repo="mlx-community/whisper-small.en-mlx",
                                 word_timestamps=True, initial_prompt=VOCAB, condition_on_previous_text=False,
                                 language="en", verbose=None)
    segs = []
    for sg in res.get("segments", []):
        words = [[round(w["start"], 2), round(w["end"], 2), w["word"].strip()] for w in sg.get("words", []) if w.get("word")]
        if sg.get("text", "").strip():
            segs.append({"start": round(sg["start"], 2), "end": round(sg["end"], 2), "text": sg["text"].strip(), "words": words})
    for p in src:
        p.unlink(missing_ok=True)          # the long audio file is not needed any more
    return {"id": s["id"], "podcast": s["series"], "title": s["title"], "language": "en",
            "duration": round(segs[-1]["end"], 1) if segs else 0, "segments": segs}


def discover_streams(reg: dict, state: dict) -> list:
    """New replays on the series' YouTube channels (Top 32 / Top 16 etc.), every 6 hours.
    They go to data/streams/mac/_found.json, which only this Mac writes."""
    found = _json_or("data/streams/mac/_found.json", {"streams": []})
    if time.time() - state.get("discovered", 0) < 6 * 3600:
        return found["streams"]
    state["discovered"] = time.time()
    known = {s.get("youtube") for s in reg.get("streams", []) + found["streams"]}
    added = []
    for ch in reg.get("channels", []):
        for line in _ytdlp_lines(["--flat-playlist", "--playlist-end", "25", "--print",
                                  "%(id)s\t%(duration)s\t%(title)s\t%(release_date,upload_date)s", ch["url"]]):
            p = line.split("\t")
            if len(p) < 4 or p[0] in known:
                continue
            dur = float(p[1]) if p[1].replace(".", "", 1).isdigit() else 0
            t, day = p[2].lower(), p[3] if p[3].isdigit() else ""
            if dur < ch.get("min_hours", 1.5) * 3600 or not any(w in t for w in ch.get("match", [])):
                continue
            if any(w in t for w in ch.get("exclude", [])):
                continue
            if day and ch.get("since") and f"{day[:4]}-{day[4:6]}-{day[6:]}" < ch["since"]:
                continue
            if not day:          # date unknown in the list: ask for it
                d = _ytdlp_lines(["--print", "%(release_date,upload_date)s", f"https://www.youtube.com/watch?v={p[0]}"])
                day = d[0] if d and d[0].isdigit() else ""
                if not day or (ch.get("since") and f"{day[:4]}-{day[4:6]}-{day[6:]}" < ch["since"]):
                    continue
            sid = "yt" + re.sub(r"[^a-z0-9]", "", p[0].lower())
            added.append({"id": sid, "series": ch["series"], "title": p[2], "event": p[2].split(" - ")[0].upper().replace("FORMULA DRIFT", "FD")[:40],
                          "date": f"{day[:4]}-{day[4:6]}-{day[6:]}", "credit": ch["credit"], "youtube": p[0],
                          "auto": True})
            known.add(p[0])
    if added:
        found["streams"] += added
        _put("data/streams/mac/_found.json", json.dumps(found, indent=1, ensure_ascii=False).encode(),
             f"mac: {len(added)} new stream(s)")
        log("nieuwe streams:", ", ".join(a["title"] for a in added))
    return found["streams"]


def streams_work(beat, state=None) -> None:
    reg = _json_or("data/streams/streams.json", {"streams": []})
    extra = discover_streams(reg, state if state is not None else {})
    for s in reg.get("streams", []) + [x for x in extra if x["id"] not in {r["id"] for r in reg.get("streams", [])}]:
        mpath = f"data/streams/mac/{s['id']}.json"
        mac = _json_or(mpath, {})
        if s.get("youtube") and mac.get("youtube") != s["youtube"]:   # a video chosen by hand always wins
            mac = {"youtube": s["youtube"], "status": "transcribing", "note": "video vastgelegd in het register"}
        if mac.get("status") == "transcribed":
            continue
        if (mac.get("status") == "error" and mac.get("version") == VERSION
                and time.time() - mac.get("at", 0) < 6 * 3600):
            continue                           # same helper failed recently; a new version tries again at once
        try:
            if not mac.get("youtube"):
                beat(f"{s['series']}: {s['title']}: zoekt de replay op YouTube", force=True)
                yid, cands = find_stream(s)
                mac.update(candidates=cands, at=time.time())
                if not yid:
                    raise RuntimeError("geen replay gevonden die bij het evenement past")
                pick = next(c for c in cands if c["id"] == yid)
                mac.update(youtube=yid, seconds=pick["seconds"], found_title=pick["title"], status="transcribing")
            if not mac.get("seconds"):
                d = _ytdlp_lines(["--print", "%(duration)s\t%(title)s", f"https://www.youtube.com/watch?v={mac['youtube']}"])
                if d and "\t" in d[0]:
                    mac.update(seconds=float(d[0].split("\t")[0] or 0), found_title=d[0].split("\t", 1)[1])
            log(f"{s['id']}: replay: {mac.get('found_title')} ({(mac.get('seconds') or 0) / 3600:.1f} uur)")
            _put(mpath, json.dumps(mac, indent=1).encode(), f"mac: stream {s['id']} {mac['youtube']}")
            beat(f"{s['series']}: {s['title']}: haalt het geluid op en transcribeert (ongeveer een kwartier)", force=True)
            t = transcribe_stream(s, mac["youtube"])
            lines, last = [f"# {s['series']}: {s['title']}", ""], -60.0
            for sg in t["segments"]:
                if sg["start"] - last >= 20:
                    last = sg["start"]
                    lines += ["", f"[{_mmss(sg['start'])}] {sg['text']}"]
                else:
                    lines.append(sg["text"])
            _put(f"data/podcasts/t/{s['id']}.json", json.dumps(t, ensure_ascii=False, separators=(",", ":")).encode(),
                 f"mac: transcript {s['id']}")
            _put(f"data/podcasts/t/{s['id']}.txt", "\n".join(lines).encode(), f"mac: transcript text {s['id']}")
            mac.update(status="transcribed", transcribed=datetime.now(timezone.utc).isoformat(), error=None)
            _put(mpath, json.dumps(mac, indent=1).encode(), f"mac: transcribed {s['id']}")
            log(f"{s['id']}: transcript klaar, {len(t['segments'])} regels")
        except Exception as ex:
            mac.update(status="error", error=str(ex)[:300], at=time.time(), version=VERSION)
            try:
                _put(mpath, json.dumps(mac, indent=1).encode(), f"mac: error {s['id']}")
            except Exception:
                pass
            log("stream fout", s["id"], ex)


# ---------- main ----------
def asset_name(ep_id: str, i: int, m: dict) -> str:
    return f"v2-{ep_id}-{i}-{int(round(m['start'] * 10))}-{int(round(m['end'] * 10))}.mp4"


def download(youtube_id: str, a: float, b: float, out: Path) -> bool:
    r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b",
                        "--merge-output-format", "mp4", "--download-sections", f"*{a:.2f}-{b:.2f}",
                        "--force-keyframes-at-cuts", "-o", str(out), f"https://www.youtube.com/watch?v={youtube_id}"],
                       capture_output=True, text=True, timeout=900)
    if r.returncode:
        log("yt-dlp:", r.stderr[-400:])
    return out.exists() and out.stat().st_size > 100_000


def self_update():
    """Every run: replace this helper with the newest version from GitHub (only if it is valid Python)."""
    try:
        new = gh("/contents/tools/mac/video_helper.py?ref=main", raw=True)
        compile(new, "video_helper.py", "exec")
        me = Path(__file__)
        if new != me.read_bytes():
            me.write_bytes(new)
            log("helper bijgewerkt; nieuwe versie start nu")
            os.execv(sys.executable, [sys.executable, str(me)])
    except Exception as ex:
        log("helper bijwerken mislukt:", ex)


def daily_update(state: dict):
    if time.time() - state.get("updated_ytdlp", 0) < 86400 or not shutil.which("brew"):
        return
    subprocess.run(["brew", "upgrade", "-q", "yt-dlp", "deno"], capture_output=True, timeout=900)
    state["updated_ytdlp"] = time.time()
    log("yt-dlp bijgewerkt")


def main():
    global KEY
    KEY = token()
    state = load_state()
    daily_update(state)
    self_update()
    rel = release()
    have = {a["name"] for a in rel.get("assets", [])}
    ix = json.loads(gh("/contents/data/podcasts/episodes.json?ref=main", raw=True))
    uploaded, errors, no_video = [], [], []
    eps: dict = {}          # per episode, shown on the dashboard
    try:
        old = json.loads(rel.get("body") or "{}")
    except Exception:
        old = {}
    last_beat = [0.0]

    def beat(now_doing: str | None = None, force: bool = False):
        if not force and time.time() - last_beat[0] < 20:
            return
        last_beat[0] = time.time()
        body = {"seen": datetime.now(timezone.utc).isoformat(), "version": VERSION, "busy": now_doing,
                "uploaded": uploaded, "errors": errors[-5:], "no_video": no_video, "episodes": eps,
                "waiting": sum(e.get("need", 0) - e.get("have", 0) for e in eps.values()),
                "last_upload": datetime.now(timezone.utc).isoformat() if uploaded else old.get("last_upload")}
        try:
            gh(f"/releases/{rel['id']}", "PATCH", {"body": json.dumps(body)})
        except Exception as ex:
            log("hartslag mislukt:", ex)

    try:
        streams_work(beat, state)          # first: transcribing a new stream
    except Exception as ex:
        log("streams:", ex)
    all_eps = list(ix["episodes"].values())
    for st in (_json_or("data/streams/streams.json", {"streams": []}).get("streams", [])
               + _json_or("data/streams/mac/_found.json", {"streams": []}).get("streams", [])):
        mac = _json_or(f"data/streams/mac/{st['id']}.json", {})
        if st.get("youtube"):
            mac["youtube"] = st["youtube"]
        if mac.get("youtube") and mac.get("status") == "transcribed":
            all_eps.append({"id": st["id"], "kind": "stream", "podcast": st["series"], "title": st["title"],
                            "youtube": mac["youtube"], "seconds": mac.get("seconds")})
    for ep in all_eps:
        try:
            moments = json.loads(gh(f"/contents/data/podcasts/moments/{ep['id']}.json?ref=main", raw=True))
        except urllib.error.HTTPError:
            continue
        live = [(i, m) for i, m in enumerate(moments) if m.get("status") in ("new", "queued")]
        if not live:
            continue
        info = eps[ep["id"]] = {"need": len(live), "state": "klaar"}
        info["have"] = sum(1 for i, m in live if asset_name(ep["id"], i, m) in have)
        todo = [(i, m) for i, m in live if asset_name(ep["id"], i, m) not in have]
        known = state.get("video", {}).get(ep["id"], {})
        info["video"] = known.get("id") if known else ep.get("youtube")
        if not todo:
            continue
        info["state"] = "zoekt de video"
        beat(f"{ep['podcast']}: {ep['title']}: zoekt de video", force=True)
        yid = ep["youtube"] if ep.get("kind") == "stream" else video_for(ep, state)
        info["video"] = yid
        if not yid:
            no_video.append(ep["id"])
            info["state"] = "geen volledige video op YouTube"
            continue
        ep = dict(ep, youtube=yid)
        theirs, ours, sound = None, None, None
        for i, m in todo:
            name = asset_name(ep["id"], i, m)
            if time.time() - state["failed"].get(name, 0) < 3600:
                info["state"] = "wacht na een fout"
                continue                               # failed recently, try again later
            info["state"] = f"haalt video op ({info['have']} van {info['need']})"
            beat(f"{ep['podcast']}: {ep['title']}: {info['state']}")
            try:
                o1 = o2 = None
                if ep.get("kind") == "stream":       # stream times ARE the video times: nothing to line up
                    o1 = o2 = 0.0
                if o1 is None and theirs is None:
                    theirs = captions(ep["youtube"])
                    if theirs:
                        ours = our_words(json.loads(gh(f"/contents/data/podcasts/t/{ep['id']}.json?ref=main", raw=True)))
                if o1 is None and theirs:
                    o1, o2 = offset_at(ours, theirs, m["start"]), offset_at(ours, theirs, m["end"] - 10)
                if o1 is None and o2 is None:            # no captions (YouTube often refuses them): match the sound
                    if sound is None:
                        info["state"] = "haalt het geluid op om de momenten te vinden"
                        beat(f"{ep['podcast']}: {ep['title']}: {info['state']}", force=True)
                        sound = (_load(podcast_audio(ep)), _load(youtube_audio(ep["youtube"])))
                    o1 = audio_offset(sound[0], sound[1], m["start"])
                    o2 = audio_offset(sound[0], sound[1], max(m["end"] - 20, m["start"]))
                    if o1 is not None or o2 is not None:
                        log(f"{name}: gevonden via het geluid")
                if o1 is None and o2 is None:
                    raise RuntimeError("moment niet teruggevonden in de video")
                o1 = o1 if o1 is not None else o2
                o2 = o2 if o2 is not None else o1
                if abs(o1 - o2) > 3:
                    log(f"{name}: begin en eind verschillen {o2 - o1:.1f} s, ik neem het begin")
                length = m["end"] - m["start"]
                a, b = m["start"] + o1, m["start"] + o1 + length
                with tempfile.TemporaryDirectory() as tmp:
                    f = Path(tmp) / name
                    if ep.get("kind") == "stream":
                        log(f"{name}: stream, video {a:.1f} tot {b:.1f}")
                        if not download(ep["youtube"], a, b, f):
                            raise RuntimeError("download mislukt")
                    else:
                        # Check on the words: take a wider piece, listen to it, and find our moment in it.
                        # Podcast files with inserted ads differ per download, so the sound match alone can be off.
                        wa, wb = max(0.0, a - 75), b + 75
                        wide = Path(tmp) / "wide.mp4"
                        if not download(ep["youtube"], wa, wb, wide):
                            raise RuntimeError("download mislukt")
                        if ours is None:
                            ours = our_words(json.loads(gh(f"/contents/data/podcasts/t/{ep['id']}.json?ref=main", raw=True)))
                        heard = heard_words(wide, wa)
                        v1 = offset_at(ours, heard, m["start"])
                        v2 = offset_at(ours, heard, max(m["end"] - 15, m["start"]))
                        if v1 is None and v2 is None:
                            raise RuntimeError("moment niet teruggevonden in de video (tekstcontrole)")
                        o = v1 if v1 is not None else v2
                        log(f"{name}: tekstcontrole {o:+.2f} s (geluid gaf {o1:+.2f} s), video {m['start'] + o:.1f}")
                        cut(wide, m["start"] + o - wa, length, f)
                    up = rel["upload_url"].split("{")[0] + "?name=" + name
                    gh("", "POST", url=up, data=f.read_bytes(), ctype="video/mp4")
                uploaded.append(name)
                info["have"] += 1
                state["failed"].pop(name, None)
                log("geupload", name)
            except Exception as ex:
                state["failed"][name] = time.time()
                errors.append(f"{name}: {ex}")
                info["error"] = str(ex)[:160]
                log("fout", name, ex)
        info["state"] = "klaar" if info["have"] >= info["need"] else info["state"]
    newly_none = set(no_video) - set(old.get("no_video") or [])
    if uploaded or newly_none:      # new video, or clips that no longer need to wait: make them now
        gh("/actions/workflows/clips.yml/dispatches", "POST", {"ref": "main"})
        log("clips worden opnieuw gemaakt")
    beat(None, force=True)
    save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as ex:
        log("gestopt:", ex)
        sys.exit(1)

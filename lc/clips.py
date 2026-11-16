"""Podcast clips, 1080x1920.

make_clip() uses the video version when there is one (YouTube), and only
falls back to an audiogram (photo + waveform) when there is no video or the
download fails. Both get the same layer on top: SIDEWAYS WIRE sticker, label
(RUMOR / THEY SAID IT / DID YOU KNOW / PODCAST CLIP), guest, topic and
captions that follow the words, in tape bars with the text centered.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from .render import Renderer

ROOT = Path(__file__).resolve().parent.parent
W, H, FPS = 1080, 1920, 30


def chunks(segments: list[dict], start: float, end: float, max_words: int = 4, max_len: float = 1.8):
    """Group the transcript words between start and end into short caption chunks.
    Returns [(t0, t1, text)] with times relative to the clip start."""
    words = [w for s in segments for w in s.get("words", []) if w[0] >= start - 0.05 and w[1] <= end + 0.3]
    out, cur = [], []
    for w in words:
        cur.append(w)
        text = " ".join(x[2] for x in cur)
        if (len(cur) >= max_words or cur[-1][1] - cur[0][0] >= max_len
                or re.search(r"[.?!,]$", w[2])):
            out.append((cur[0][0] - start, cur[-1][1] - start, text))
            cur = []
    if cur:
        out.append((cur[0][0] - start, cur[-1][1] - start, " ".join(x[2] for x in cur)))
    # close small gaps so captions do not flicker
    fixed = []
    for i, (a, b, t) in enumerate(out):
        nxt = out[i + 1][0] if i + 1 < len(out) else b + 0.4
        fixed.append((max(0.0, a), min(nxt, b + 0.4) if nxt - b < 0.6 else b + 0.2,
                      t.upper().strip(" ,")))
    return fixed


def _ff(args: list[str]):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])


def _download_video(youtube_id: str, start: float, end: float, out: Path) -> bool:
    """Only the needed part of the video. YouTube may block servers: then False."""
    cmd = ["yt-dlp", "-q", "--no-warnings", "-f", "bv*[height<=1080]+ba/b", "--merge-output-format", "mp4",
           "--download-sections", f"*{start:.2f}-{end:.2f}", "--force-keyframes-at-cuts",
           "-o", str(out), f"https://www.youtube.com/watch?v={youtube_id}"]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        return out.exists() and out.stat().st_size > 100_000
    except Exception:
        return False


def make_clip(ep: dict, transcript: dict, moment: dict, out: str, photo: str | None = None,
              allow_video: bool = False, video_src: Path | str | None = None) -> dict:
    """moment: {start, end, kind, guest, topic, credit}. Returns {"mode", "out", "captions"}."""
    start, end = float(moment["start"]), float(moment["end"])
    length = end - start
    caps = chunks(transcript["segments"], start, end)
    with tempfile.TemporaryDirectory() as tmp, Renderer() as r:
        tmp = Path(tmp)
        video = Path(video_src) if video_src else None   # cut by the Mac helper, already aligned
        if not video and allow_video and ep.get("youtube"):   # direct download, usually blocked on servers
            v = tmp / "src.mp4"
            if _download_video(ep["youtube"], start, end, v):
                video = v
        mode = "video" if video else "audiogram"
        data = {"w": W, "h": H, "bg": "transparent", "podcast": ep["podcast"], "guest": moment.get("guest", ""),
                "topic": moment.get("topic"), "kind": moment.get("kind", "moment"),
                "credit": moment.get("credit") or ep.get("credit"), "audiogram": mode == "audiogram", "photo": photo,
                "stream": ep.get("kind") == "stream", "event": ep.get("event")}
        r.render("clip_overlay.html", data, tmp / "layer.png", transparent=True)
        # Context photos (added by Joshua in the podcast studio), shown one after another
        photos = []
        for k, ph in enumerate(moment.get("photos") or []):
            src = (ROOT / ph["src"]) if not str(ph["src"]).startswith("http") else None
            if src is None or not src.exists():
                continue
            f = tmp / f"photo{k}.png"
            r.render("photo_card.html", {"w": 500, "h": 620, "bg": "transparent", "src": src.as_uri(),
                                         "credit": ph.get("credit", ""), "tilt": 3 if k % 2 == 0 else -3}, f, transparent=True)
            photos.append((ph, f))
        cap_files = []
        for i, (_, _, text) in enumerate(caps):
            f = tmp / f"cap{i:03d}.png"
            r.render("caption.html", {"w": W, "h": 260, "bg": "transparent", "text": text}, f, transparent=True)
            cap_files.append(f)

        inputs, filt = [], []
        if video:
            inputs += ["-i", str(video)]
            filt.append(f"[0:v]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,"
                        f"eq=brightness=-0.25,scale={W}:{H},fps={FPS},setsar=1[bg];"
                        f"[0:v]scale={W}:-2,fps={FPS},setsar=1[fg];[bg][fg]overlay=0:500[base]")
            audio = "0:a"
            cap_y = 1180
        else:
            inputs += ["-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", ep["audio"]]
            filt.append(f"color=c=0x151517:s={W}x{H}:r={FPS}:d={length:.2f}[bg0];"
                        f"[0:a]showwaves=s=840x130:mode=cline:draw=full:rate={FPS}:colors=0xC6FF00:scale=sqrt,format=rgba[wave];"
                        f"[bg0][wave]overlay=70:975[base]")
            audio = "0:a"
            cap_y = 1180
        n = 1
        inputs += ["-loop", "1", "-t", f"{length:.2f}", "-i", str(tmp / "layer.png")]
        filt.append(f"[base][{n}:v]overlay=0:0:format=auto[l0]")
        last = "l0"
        if photos:
            win0, win1 = 1.5, max(length - 1.0, 2.0)
            step = (win1 - win0) / len(photos)
            px, py = (560, 470) if video else (290, 450)    # video: over the host's half; audiogram: centre
            for k, (ph, f) in enumerate(photos):
                a = float(ph["in"]) if ph.get("in") not in (None, "") else win0 + k * step       # chosen in the studio
                b = float(ph["out"]) if ph.get("out") not in (None, "") else win0 + (k + 1) * step
                a, b = max(0.0, min(a, length)), max(0.0, min(b, length))
                if b - a < 0.3:
                    continue
                n += 1
                inputs += ["-loop", "1", "-t", f"{length:.2f}", "-i", str(f)]
                filt.append(f"[{last}][{n}:v]overlay={px}:{py}:format=auto:enable='between(t,{a:.2f},{b:.2f})'[p{k}]")
                last = f"p{k}"
        if cap_files:
            # All captions as ONE image sequence (with see-through gaps) instead of one input per caption:
            # ffmpeg then decodes one small stream, which is many times faster.
            blank = tmp / "blank.png"          # a see-through image, made with ffmpeg (no extra library needed)
            _ff(["-f", "lavfi", "-i", f"color=c=black@0.0:s={W}x260,format=rgba", "-frames:v", "1", str(blank)])
            lines, cur = [], 0.0
            for (a, b, _), f in zip(caps, cap_files):
                a, b = max(a, cur), max(b, a)
                if a - cur > 0.01:
                    lines += [f"file '{blank}'", f"duration {a - cur:.3f}"]
                if b - a > 0.01:
                    lines += [f"file '{f}'", f"duration {b - a:.3f}"]
                cur = b
            lines += [f"file '{blank}'", f"duration {max(length - cur, 0.1):.3f}", f"file '{blank}'"]
            (tmp / "caps.txt").write_text("\n".join(lines) + "\n")
            n += 1
            inputs += ["-f", "concat", "-safe", "0", "-i", str(tmp / "caps.txt")]
            filt.append(f"[{n}:v]fps={FPS},format=rgba[cap];[{last}][cap]overlay=0:{cap_y}:format=auto:eof_action=pass[c0]")
            last = "c0"
        filt.append(f"[{last}]format=yuv420p[v]")
        _ff([*inputs, "-filter_complex", ";".join(filt), "-map", "[v]", "-map", audio,
             "-t", f"{length:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out])
    return {"mode": mode, "out": out, "captions": len(caps)}

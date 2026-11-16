"""Video tools for Sideways Wire reels, built on ffmpeg.

- find_initiation(): finds the moment a run starts from the audio
  (the engine hitting the limiter is the loudest sudden rise).
- battle_reel(): stacks run 1 above run 2, synced at initiation,
  and lays the rendered overlay PNG on top. Output: 1080x1920 H.264.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

FPS = 30
HALF_H = 950          # height of each run in the stacked reel
GAP = 20              # black bar between the runs
W, H = 1080, 1920


def _run(cmd: list[str]) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{res.stderr[-2000:]}")
    return res.stdout


def duration(path: str | Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)])
    return float(json.loads(out)["format"]["duration"])


def _audio_envelope(path: str | Path, rate: int = 8000, win: float = 0.05) -> tuple[np.ndarray, float]:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    n = int(rate * win)
    frames = len(a) // n
    rms = np.sqrt((a[: frames * n].reshape(frames, n) ** 2).mean(axis=1) + 1e-12)
    return rms, win


def find_initiation(path: str | Path) -> float:
    """Seconds into the clip where the run starts: the biggest jump in loudness."""
    rms, win = _audio_envelope(path)
    db = 20 * np.log10(rms)
    edge = int(0.2 / win)                      # ignore codec artefacts at start/end
    core = db[edge:len(db) - edge] if len(db) > 3 * edge else db
    smooth = np.convolve(core, np.ones(3) / 3, mode="same")
    quiet, loud = np.percentile(smooth, 20), np.percentile(smooth, 90)
    if loud - quiet < 6:                        # no clear onset: let Joshua check
        return 0.0
    threshold = quiet + (loud - quiet) / 2
    # First moment the sound stays above the threshold for at least 0.3 s.
    hold = max(1, int(0.3 / win))
    above = smooth > threshold
    for i in range(len(above) - hold):
        if above[i:i + hold].all():
            return (i + edge) * win
    return 0.0


def battle_reel(run1: str, run2: str, overlay_png: str, out: str,
                offset1: float | None = None, offset2: float | None = None,
                lead_in: float = 1.0, length: float | None = None,
                nudge: float = 0.0) -> dict:
    """Make the stacked battle reel.

    offset1/offset2: initiation time per run (found automatically if None).
    lead_in: seconds shown before initiation. nudge: extra shift for run 2,
    used by Joshua's Telegram buttons ("run 2 a bit earlier/later").
    """
    o1 = find_initiation(run1) if offset1 is None else offset1
    o2 = (find_initiation(run2) if offset2 is None else offset2) + nudge
    s1, s2 = max(0.0, o1 - lead_in), max(0.0, o2 - lead_in)
    if length is None:
        length = min(duration(run1) - s1, duration(run2) - s2)
    fit = (f"scale={W}:{HALF_H}:force_original_aspect_ratio=increase,"
           f"crop={W}:{HALF_H},fps={FPS},setsar=1")
    filt = (
        f"[0:v]trim=start={s1:.3f}:duration={length:.3f},setpts=PTS-STARTPTS,{fit}[top];"
        f"[1:v]trim=start={s2:.3f}:duration={length:.3f},setpts=PTS-STARTPTS,{fit}[bot];"
        f"color=c=0x111111:s={W}x{H}:r={FPS}:d={length:.3f}[bg];"
        f"[bg][top]overlay=0:0[t1];[t1][bot]overlay=0:{HALF_H + GAP}[t2];"
        f"[t2][2:v]overlay=0:0:format=auto,format=yuv420p[v];"
        # Audio: run 1 sound, so the reel keeps the real engine noise.
        f"[0:a]atrim=start={s1:.3f}:duration={length:.3f},asetpts=PTS-STARTPTS[a]"
    )
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", run1, "-i", run2, "-loop", "1", "-i", overlay_png,
        "-filter_complex", filt, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
        "-t", f"{length:.3f}", "-movflags", "+faststart", out,
    ])
    return {"out": out, "initiation_run1": round(o1, 2), "initiation_run2": round(o2, 2),
            "start_run1": round(s1, 2), "start_run2": round(s2, 2), "length": round(length, 2)}

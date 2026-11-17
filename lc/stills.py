"""Stills from livestream footage, used as photos for posts.

We may use FD and Drift Masters livestream footage with credit to the series, so when a battle or
livestream moment is made into a reel, a few sharp frames are saved as 4:5 stills
(docs/media/stills/) and indexed by the drivers in them (data/stills.json).
A news post about one of those drivers then gets a still instead of the text-only design.
Joshua can always replace it with his own photo on the dashboard.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "docs" / "media" / "stills"
INDEX = ROOT / "data" / "stills.json"


def _key(name: str) -> str:
    from .handles import _key as k
    return k(name)


def index() -> dict:
    return json.loads(INDEX.read_text()) if INDEX.exists() else {}


def _sharpness(path: str) -> float:
    """Score a frame: sharp, colourful detail in the middle band (where the cars are), not empty asphalt or sky."""
    import numpy as np
    from PIL import Image, ImageFilter
    im = Image.open(path).convert("RGB").resize((270, 338))
    mid = im.crop((20, 60, 250, 260))
    edges = np.asarray(mid.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float32)
    a = np.asarray(mid, dtype=np.float32)
    rg, yb = a[..., 0] - a[..., 1], 0.5 * (a[..., 0] + a[..., 1]) - a[..., 2]
    colour = np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    top = np.asarray(im.crop((0, 0, 270, 110)), dtype=np.float32)
    sky = ((top[..., 2] > top[..., 0] + 25) & (top[..., 2] > 150)).mean()   # wide shots of the start line: mostly sky
    return float(edges.mean() * (10 + colour) * (1 - sky))


def grab(video: str, times: list[float], name: str, people: list[str], credit: str, keep: int = 2) -> list[str]:
    """Save the sharpest `keep` frames (4:5, centre crop, no telemetry corner) and index them."""
    DIR.mkdir(parents=True, exist_ok=True)
    found = []
    with tempfile.TemporaryDirectory() as tmp:
        for k, t in enumerate(times):
            f = str(Path(tmp) / f"{k}.jpg")
            # 16:9 frame -> 4:5: take a 0.5625-wide slice a little left of centre (the telemetry dial sits bottom right)
            r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.2f}", "-i", video, "-frames:v", "1",
                                "-vf", "crop=ih*0.8:ih:(iw-ih*0.8)*0.42:0,scale=1080:1350:flags=lanczos,unsharp=5:5:0.5",
                                "-q:v", "2", f], capture_output=True)
            if r.returncode == 0 and Path(f).exists():
                found.append((_sharpness(f), f))
        out = []
        for n, (_, f) in enumerate(sorted(found, reverse=True)[:keep]):
            dest = DIR / f"{name}-{n}.jpg"
            dest.write_bytes(Path(f).read_bytes())
            out.append(str(dest.relative_to(ROOT)))
    if out:
        ix = index()
        for p in people:
            lst = ix.setdefault(_key(p), [])
            for o in out:
                if not any(e["src"] == o for e in lst):
                    lst.append({"src": o, "credit": credit, "people": people})
        INDEX.write_text(json.dumps(ix, indent=1, ensure_ascii=False))
    return out


def pick(people: list[str], used: set[str] | None = None) -> dict | None:
    """A still for the first person that has one, preferring stills with only that person's battle."""
    ix, used = index(), used or set()
    for p in people:
        for e in ix.get(_key(p), []):
            if e["src"] not in used and (ROOT / e["src"]).exists():
                return e
    return None

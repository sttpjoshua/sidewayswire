"""Turns podcast moments into clips and queues them as posts.

The editor writes data/podcasts/moments/<episode id>.json:
[
  {"start": 1834.2, "end": 1872.0,          # seconds in the episode, cut on whole sentences
   "kind": "rumor" | "quote" | "fact" | "moment",
   "guest": "JACK SHANAHAN", "topic": "A NEW CAR FOR 2027?",
   "quote": "the exact words, from the transcript",
   "why": "one line: why this is interesting for the channel",
   "credit": "@formulad", "caption": "post text with credits and hashtags",
   "status": "new"}                          # new -> clip made -> queued
]
Rumors always go to Joshua on Telegram first (check=true in the queued post).
Clips are 15 to 75 seconds.
"""
from __future__ import annotations

import json
import re
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import progress
from . import queue as q
from .clips import make_clip, make_split
from . import streams
from . import handles
from .podcasts import DIR, load_index

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"


LAYOUT = 4                 # raise when the clip design changes: unposted clips are made again
NO_PICTURE = "geen beeld"
WAIT_VIDEO = 3 * 3600      # how long a YouTube episode waits for the Mac helper before we fall back to audiogram
TAG = "video-sources"


def asset_name(ep_id: str, i: int, m: dict) -> str:
    """Must match tools/mac/video_helper.py: changing start or end asks for a new video."""
    return f"v2-{ep_id}-{i}-{int(round(float(m['start']) * 10))}-{int(round(float(m['end']) * 10))}.mp4"


NAME_DOUBT = re.compile(r"spell|spelling|naam|name|surname|transcri|spraak|speech|mueller|muller", re.I)


def names_settled(m: dict, post: dict) -> bool:
    """True when the only reason to check was a doubt about how a name is spelled, and every person
    in the moment is now known in the people database (official spelling, alias or one clear near match)."""
    if post.get("check_reason") != "namen nakijken" or m.get("kind") == "rumor" or m.get("by") == "joshua":
        return False
    why = m.get("check_reason") or ""
    if why and not NAME_DOUBT.search(why):
        return False                    # e.g. who is speaking: that stays with Joshua
    reg = handles.registry()
    names = handles.people(m)
    return bool(names) and all(handles.lookup(reg, n) for n in names) and not post.get("missing_handles")


def pieces(ep_id: str, i: int, m: dict) -> list[str]:
    """Must match tools/mac/video_helper.py pieces(): one piece, or one per run for a split battle."""
    if m.get("split"):
        return [f"v2-{ep_id}-{i}r{k + 1}-{int(round(float(r['start']) * 10))}-{int(round(float(piece_end(m, k)) * 10))}.mp4"
                for k, r in enumerate(m["split"]["runs"])]
    return [asset_name(ep_id, i, m)]


def piece_end(m: dict, k: int) -> float:
    """Run 2's piece runs on to the judges' call (lc/results.py). Must match tools/mac/video_helper.py."""
    r = m["split"]["runs"][k]
    res = m["split"].get("result")
    return max(float(r["end"]), float(res["to"])) if res and k == len(m["split"]["runs"]) - 1 else float(r["end"])


def video_assets() -> tuple[dict, list]:
    """({name: download url} of the videos the Mac helper uploaded, [episode ids without a full video])."""
    import requests
    repo = os.environ.get("GITHUB_REPOSITORY", "sttpjoshua/sidewayswire")
    h = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GH_TOKEN"):
        h["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/releases/tags/{TAG}", headers=h, timeout=30)
        if r.ok:
            try:
                beat = json.loads(r.json().get("body") or "{}")
            except ValueError:
                beat = {}
            seen = beat.get("seen")
            alive = bool(seen) and (datetime.now(timezone.utc) - datetime.fromisoformat(seen)).total_seconds() < 3600
            return ({a["name"]: a["browser_download_url"] for a in r.json().get("assets", [])},
                    (beat.get("no_video") or []) if alive else None)
    except Exception as e:
        print("video assets:", e)
    return {}, None


def _fetch(url: str, out: Path) -> Path:
    import requests
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for c in r.iter_content(1 << 20):
                f.write(c)
    return out


def save_partial(note: str):
    """In GitHub Actions: commit and push what is done so far, so new clips show up on the dashboard
    during a long run instead of only at the end."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    try:
        from . import gitsave, mediastore, status
        print("media:", mediastore.sync())
        status.run()
        gitsave.save(f"clips: {note}", ["data/podcasts", "queue", "docs/media", "docs/status.json"])
    except Exception as e:
        print("save:", e)


def run(limit: int = 120) -> dict:
    ix = load_index()
    ix["episodes"] = {**ix["episodes"], **streams.episodes()}      # livestreams are made the same way
    report = {"clips": [], "errors": [], "waiting_for_video": []}
    assets, no_video = video_assets()
    now = datetime.now(timezone.utc)
    files, tasks = {}, []           # moments per episode file, and the clips to make
    # 1. Decide what to make (cheap), so the dashboard can show "12 of 70"
    for mf in sorted((DIR / "moments").glob("*.json")):
        ep = ix["episodes"].get(mf.stem)
        tf = DIR / "t" / f"{mf.stem}.json"
        if not ep or not tf.exists():
            continue
        moments = files[mf] = json.loads(mf.read_text())
        hf = DIR / "hooks" / f"{mf.stem}.json"          # hooks chosen afterwards (the moment's own hook wins)
        hooks = json.loads(hf.read_text()) if hf.exists() else {}
        for i, m in enumerate(moments):
            if not m.get("hook") and hooks.get(str(i)):
                m["hook"] = hooks[str(i)]
            hook_sig = json.dumps(m.get("hook") or {}, sort_keys=True)
            pid = f"pod-{mf.stem}-{i}"
            qp = q.QUEUE / f"{pid}.json"
            post = json.loads(qp.read_text()) if qp.exists() else None
            if post and post.get("status") not in ("posted", "skipped") and m.get("status") != "skipped":
                cap, tags, missing = handles.compose(ep, m)       # tags always from the checked registry
                if post.get("caption_by") == "joshua":    # his own text stays; only the tag info is refreshed
                    cap = post.get("caption")
                ppl = handles.people(m)[:6]
                changed = (post.get("caption") != cap or post.get("missing_handles") != missing
                           or post.get("tags") != tags or post.get("people") != ppl)
                if changed:
                    post.update(caption=cap, tags=tags, missing_handles=missing, people=ppl)
                if post.get("status") == "check" and names_settled(m, post):
                    # Joshua (25 nov): the people database answers the editor's spelling question, so the
                    # post no longer waits for him; build.py treats it as a normal post on the next run.
                    post.update(status="draft", check=False, check_reason="", names_by="people database")
                    m["check"] = False
                    changed = True
                if changed:
                    q.save(post)
            if m.get("status") == "skipped":
                if post and post.get("status") not in ("posted", "skipped"):
                    post["status"] = "skipped"
                    q.save(post)
                continue
            need = pieces(mf.stem, i, m)
            name = need[-1]
            if not all(n in assets for n in need):
                assets = {k: v for k, v in assets.items() if k != name}   # all runs or nothing
            joshua_skipped = bool(post) and post.get("status") == "skipped" and post.get("skip_reason") != NO_PICTURE
            upgrade = (m.get("status") == "queued" and not (post and post.get("status") == "posted") and not joshua_skipped
                       and ((m.get("mode") == "audiogram" and name in assets) or m.get("layout", 1) < LAYOUT
                            or m.get("redo")
                            or m.get("hook_sig", json.dumps({})) != hook_sig))
            retry = m.get("status") == "error" and m.get("tries", 0) < 3 and "already posted" not in (m.get("error") or "")
            if not (m.get("status", "new") == "new" or upgrade or retry) or len(tasks) >= limit:
                continue
            if post and post.get("status") == "posted":
                m.update(status="error", error="this clip is already posted; add a new moment instead")
                continue
            length = float(m["end"]) - float(m["start"])
            if not m.get("split") and not 10 <= length <= 90:
                m.update(status="error", error=f"clip length {length:.0f}s, keep it 15-75 s")
                continue
            wants_video = ep.get("kind") in ("stream", "vlog") or (no_video is not None and mf.stem not in no_video)
            if upgrade and wants_video and name not in assets:
                continue                           # keep the current clip until the checked video piece is there
            if m.get("wait_name") != name:
                m.pop("wait_video", None)          # new piece asked for: start the waiting time again
                m["wait_name"] = name
            if ep.get("kind") in ("stream", "vlog") and name not in assets:
                report["waiting_for_video"].append(pid)
                continue                           # a stream clip needs the footage, there is no audio-only version
            if name not in assets:
                # Joshua (25 nov): no content without picture. No audiogram any more: a moment waits for
                # its video, and an episode that has no video on YouTube gives no clips at all.
                if no_video is not None and mf.stem in no_video:
                    m.update(status="skipped", skip_reason=NO_PICTURE)
                    if post and post.get("status") not in ("posted", "skipped"):
                        post.update(status="skipped", skip_reason=NO_PICTURE)
                        q.save(post)
                else:
                    m.setdefault("wait_video", now.isoformat())
                    report["waiting_for_video"].append(pid)
                continue
            tasks.append((mf, ep, tf, i, m, post, name, upgrade))
    for mf, moments in files.items():
        mf.write_text(json.dumps(moments, indent=1, ensure_ascii=False))
    # Order: Joshua's own edits first, then clips that already existed (new design), then new clips
    tasks.sort(key=lambda t: (t[4].get("by") != "joshua", not t[7], t[4].get("status") != "queued"))

    # 2. Make them, with progress and a save every few clips
    transcripts, t_start = {}, time.time()
    remake = sum(1 for t in tasks if t[7])
    for done, (mf, ep, tf, i, m, post, name, upgrade) in enumerate(tasks):
        pid = f"pod-{mf.stem}-{i}"
        per = (time.time() - t_start) / done if done else 60.0
        progress.update(force=True, phase="clips", episode=mf.stem, title=ep["title"], podcast=ep["podcast"],
                        clip=i, done=done, total=len(tasks), remake=remake, pct=round(done / len(tasks), 3),
                        eta=round(per * (len(tasks) - done)), topic=m.get("topic"))
        if mf.stem not in transcripts:
            transcripts[mf.stem] = json.loads(tf.read_text())
        out = MEDIA / pid / "clip.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                if m.get("split"):
                    runs = [_fetch(assets[n], Path(tmp) / f"run{k}.mp4") for k, n in enumerate(pieces(mf.stem, i, m), 1)]
                    res = make_split(ep, m, runs, str(out))
                    try:                                  # stills for posts about these drivers
                        from . import stills
                        for k, (run, r) in enumerate(zip(runs, m["split"]["runs"]), 1):
                            o = float(r["init"]) - float(r["start"])
                            stills.grab(run, [o + x * 1.5 for x in range(2, 16)], f"{mf.stem}-{i}r{k}",
                                        m.get("people") or m["split"]["lead"], ep.get("credit") or "")
                    except Exception as ex:
                        print("stills:", ex)
                else:
                    src = _fetch(assets[name], Path(tmp) / "src.mp4") if name in assets else None
                    res = make_clip(ep, transcripts[mf.stem], m, str(out), photo=ep.get("art"), video_src=src)
            m.pop("wait_video", None)
            m.pop("error", None)
            m.pop("tries", None)
            m.pop("redo", None)
            m.update(status="queued", clip=str(out.relative_to(ROOT)), mode=res["mode"], layout=LAYOUT,
                     hook_sig=json.dumps(m.get("hook") or {}, sort_keys=True),
                     made=datetime.now(timezone.utc).isoformat())
            cap, tags, missing = handles.compose(ep, m)
            check = (m["kind"] == "rumor" or res["mode"] == "audiogram"
                     or bool(m.get("check"))) and m.get("by") != "joshua"
            keep = bool(post) and post.get("status") in ("ready", "approved") and post.get("post_at") and not check
            q.save({                                     # a remake keeps its place in the content calendar
                "id": pid, "kind": {"stream": "stream_clip", "vlog": "vlog_clip"}.get(ep.get("kind"), "podcast_clip"),
                "status": "ready" if keep else "draft", **({"post_at": post["post_at"]} if keep else {}),
                "slides": [], "title": m.get("topic"),
                "video": str(out.relative_to(ROOT)), "caption": cap, "tags": tags, "missing_handles": missing, "format": "split" if m.get("split") else "single",
                "credit": m.get("credit"), "check": check,
                "check_reason": ("gerucht uit een podcast" if m["kind"] == "rumor"
                                 else "namen nakijken" if m.get("check")
                                 else "audiogram: er was geen video" if res["mode"] == "audiogram" else ""),
                # Vlog clips never go back to YouTube itself (the maker's own footage: Content ID claims).
                "platforms": ["instagram", "facebook", "tiktok"] + ([] if ep.get("kind") == "vlog" else ["youtube"]),
                "source": {"podcast": ep["podcast"], "episode": ep["title"], "start": m["start"]},
                "created": (post or {}).get("created") or datetime.now(timezone.utc).isoformat(),
                "built": datetime.now(timezone.utc).isoformat(),
                # Joshua's platform choice and the plan survive a remake; the short version is made again.
                **{k: post[k] for k in ("ig", "pinned_at", "plan") if keep and post.get(k)},
            })
            report["clips"].append(f"{pid} ({res['mode']}{', upgraded' if upgrade else ''})")
        except Exception as e:
            m.update(status="error", error=str(e)[:200], tries=m.get("tries", 0) + 1)
            report["errors"].append(f"{pid}: {e}")
        mf.write_text(json.dumps(files[mf], indent=1, ensure_ascii=False))
        if (done + 1) % 4 == 0 or done + 1 == len(tasks):
            save_partial(f"{done + 1} of {len(tasks)}")
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))

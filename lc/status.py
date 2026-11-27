"""Writes docs/status.json for the dashboard and sends the daily Telegram summary."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import mediastore
from . import queue as q

ROOT = Path(__file__).resolve().parent.parent


def stream_summary() -> dict:
    """How far the livestreams are: found, turned into text, moments picked."""
    try:
        from . import streams
        items = streams.registry()
    except Exception:
        return {}
    out = {"total": len(items), "transcribed": 0, "moments": 0, "next": None, "series": {}}
    for st in sorted(items, key=lambda x: x.get("date", ""), reverse=True):
        mac = ROOT / "data" / "streams" / "mac" / f"{st['id']}.json"
        done = mac.exists() and json.loads(mac.read_text()).get("status") == "transcribed"
        has_m = (ROOT / "data" / "podcasts" / "moments" / f"{st['id']}.json").exists()
        out["transcribed"] += done
        out["moments"] += has_m
        ser = out["series"].setdefault(st.get("series", "?"), {"total": 0, "transcribed": 0})
        ser["total"] += 1; ser["transcribed"] += done
        if not done and not out["next"]:
            out["next"] = st.get("title")
    return out


def photo_info(p: dict):
    """For news posts: does it have a photo, and whose (for the dashboard's photo button)."""
    sl = (p.get("slides") or [{}])[0]
    if sl.get("template") not in ("news.html", "news_text.html", "hook.html"):
        return None
    d = sl.get("data") or {}
    if sl["template"] == "hook.html":          # kop-post: a photo is optional, except for a new car or livery
        mode = "joshua" if p.get("photo_by") == "joshua" else "auto" if d.get("photo") else \
            "none" if (p.get("hook") or {}).get("type") == "look" else "optional"
        return {"mode": mode, "credit": d.get("photo_credit", "")}
    mode = "none" if sl["template"] == "news_text.html" else "joshua" if p.get("photo_by") == "joshua" else "auto" if p.get("photo_auto") else "set"
    return {"mode": mode, "credit": d.get("photo_credit", "")}


def podcast_status() -> dict:
    d = ROOT / "data" / "podcasts"
    if not (d / "episodes.json").exists():
        return {"feeds": {}, "episodes": []}
    ix = json.loads((d / "episodes.json").read_text())
    from . import streams
    allep = {**ix["episodes"], **streams.episodes()}
    eps = []
    for e in sorted(allep.values(), key=lambda e: e["published"] or "", reverse=True)[:60]:
        mf = d / "moments" / f"{e['id']}.json"
        moments = json.loads(mf.read_text()) if mf.exists() else []
        eps.append({k: e.get(k) for k in ("id", "podcast", "title", "published", "status", "youtube",
                                          "audio", "link", "art", "seconds", "error", "transcribed", "tries", "kind", "credit", "event")}
                   | {"has_transcript": (d / "t" / f"{e['id']}.txt").exists(),
                      "moments": [{k: m.get(k) for k in ("start", "end", "kind", "guest", "topic", "quote",
                                                         "why", "status", "clip", "mode", "wait_video")} | {"split": bool(m.get("split"))} for m in moments]})
    feeds = {n: {k: f.get(k) for k in ("title", "episodes", "error", "ok")} for n, f in ix["feeds"].items()}
    return {"feeds": feeds, "episodes": eps}


def shown_posts(posts: list[dict]) -> list[dict]:
    """Everything that is still to come (planned, in stock, to review) plus the 150 latest posted."""
    key = lambda p: p.get("posted_at") or p.get("post_at") or p.get("built") or p.get("created") or ""
    live = [p for p in posts if p.get("status") not in ("posted", "skipped")]
    done = sorted((p for p in posts if p.get("status") in ("posted", "skipped")), key=key, reverse=True)[:150]
    return sorted(live + done, key=key, reverse=True)


def _replies() -> list[dict]:
    """Reply suggestions on our own posts that wait for Joshua (lc/engage.py, written by the local editor)."""
    try:
        from . import engage
        return [x for x in engage.pending() if x.get("status") == "suggested"][:60]
    except Exception:
        return []


def _names(posts: list[dict]) -> list[dict]:
    try:
        from . import handles
        return handles.open_names(posts)
    except Exception as e:
        print("names:", e)
        return []


def run(folder: Path = q.QUEUE, out: Path = ROOT / "docs" / "status.json") -> dict:
    from . import rights
    posts = q.load(folder=folder)
    perms = rights.permitted()
    inbox = ROOT / "data" / "inbox.json"
    ib = json.loads(inbox.read_text()) if inbox.exists() else {}
    stories = ib.get("stories", [])
    def clip_title(p):            # podcast clips: the headline of the moment
        if p.get("title") or p.get("kind") != "podcast_clip":
            return p.get("title")
        try:
            _, ep, i = p["id"].split("-")
            return json.loads((ROOT / "data" / "podcasts" / "moments" / f"{ep}.json").read_text())[int(i)].get("topic")
        except Exception:
            return None
    keep = ("id", "kind", "status", "post_at", "posted_at", "caption", "media", "problems", "results", "credit",
            "check", "check_reason", "source", "platforms", "created", "built", "want_at", "video", "tags", "missing_handles", "caption_by", "format",
            "plan", "score", "captions", "ig", "collaborators", "people", "moment_kind", "pinned_at", "short_none", "short_len", "thumb", "preview", "hook", "evergreen", "tiktok_done")
    status = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "media_repo": mediastore.PUBLIC_REPO if mediastore.public() else mediastore.REPO,
        "counts": dict(Counter(p.get("status", "draft") for p in posts)),
        "collected": ib.get("updated"),
        "instagram": ib.get("instagram", False),
        "sources": ib.get("sources", []),
        "inbox": [{k: s.get(k) for k in ("title", "series", "buzz", "published", "items")} for s in stories[:80]],
        "podcasts": podcast_status(),
        "streams": stream_summary(),
        "posts": [{k: p.get(k) for k in keep} | {"media": [mediastore.url(m) for m in p.get("media") or []],
                                                 "video": mediastore.url(p["video"]) if p.get("video") else None,
                                                 "short": mediastore.url(p["short"]) if p.get("short") else None,
                                                 "thumb": p["thumb"].removeprefix("docs/") if p.get("thumb") else None,
                                                 "title": clip_title(p), "photo": photo_info(p),
                                                 "rights": rights.rights_of(p, perms)}
                  for p in shown_posts(posts)],
        "replies": _replies(),
        "names": _names(posts),
        "keys": json.loads((ROOT / "data" / "keys.json").read_text()) if (ROOT / "data" / "keys.json").exists() else {},
        "drivers": _drivers(),
        "money": _money(posts),
        "weekly": _weekly(),
        "channels": json.loads((ROOT / "data" / "channels.json").read_text()) if (ROOT / "data" / "channels.json").exists() else {},
    }
    out.write_text(json.dumps(status, indent=1, ensure_ascii=False), encoding="utf-8")
    return status["counts"]


def _weekly() -> dict | None:
    try:
        from . import weekly
        return weekly.latest()
    except Exception as e:
        return {"error": str(e)[:200]}


def _money(posts) -> dict:
    try:
        from . import milestones
        return milestones.build(posts)
    except Exception as e:
        return {"error": str(e)[:200]}


def _drivers() -> list[dict]:
    """Drivers with a race number (data/sources.csv), for the cars on the terrain in the kantoor."""
    import csv
    out = []
    try:
        for r in csv.DictReader(open(ROOT / "data" / "sources.csv", encoding="utf-8")):
            if r.get("Nr", "").strip():
                out.append({"name": r["Naam"], "nr": r["Nr"].strip(), "land": r.get("Land", ""), "serie": r.get("Serie", ""),
                            "prio": r.get("Prioriteit", ""), "aliases": r.get("Aliassen", "")})
    except Exception:
        pass
    return out


if __name__ == "__main__":
    print(run())

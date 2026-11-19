"""Talking with the community on our own posts (Joshua, 19 nov 2026, learned from DriftReady).

What DriftReady does and we copy: the page likes almost every comment, puts a "follow us" comment under
each post, and answers the best comments short and human, sometimes with a question back. What we do not
copy: an AI that posts opinions in our name on its own. So:

- Facebook: every comment from someone else gets a like from the page (automatic).
- Facebook: right after posting, one first comment with a follow call (automatic).
- Facebook and Instagram: the best comments (long, or with likes) land in data/replies.json; the local
  editor on the Mac writes a short reply; Joshua approves, edits or skips it on the dashboard (BEOORDELEN);
  only approved replies are sent, by this module.

Instagram does not let a page like comments through the API, so there it is replies only.
In the test phase (LC_DRY_RUN, until 1 December) nothing is sent: there are no live posts yet.

    python -m lc.engage
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from . import queue as q

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "data" / "replies.json"
SUGGESTED = ROOT / "data" / "replies_suggested.json"     # written by the local editor on the Mac
DECISIONS = ROOT / "data" / "replies_decisions.json"     # written by the dashboard (Joshua)
GRAPH = "https://graph.facebook.com/v21.0"
DAYS = 7                     # we keep talking under a post for a week
MAX_LIKES = 80               # per run, stays well under Meta's limits
PER_POST = 5                 # reply suggestions per post per platform
FIRST_COMMENTS = [
    "👉 Follow Sideways Wire for daily drift news, battles and the best runs.",
    "Follow Sideways Wire so you never miss a battle, a transfer or a new build 🔥",
    "New here? Follow Sideways Wire: drift news from FD, Drift Masters and beyond, every day.",
]


def load() -> dict:
    d = json.loads(FILE.read_text()) if FILE.exists() else {}
    d.setdefault("items", [])
    d.setdefault("liked", [])
    d.setdefault("first", {})
    return d


def save(d: dict) -> None:
    d["liked"] = d["liked"][-4000:]
    cut = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    d["items"] = [x for x in d["items"] if x.get("status") in ("new", "suggested", "approved") or x.get("created", "") > cut]
    FILE.parent.mkdir(exist_ok=True)
    FILE.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n")


def merge(d: dict) -> int:
    """Takes in the Mac's reply drafts and Joshua's decisions (separate files, so nobody overwrites anybody)."""
    sug = json.loads(SUGGESTED.read_text()) if SUGGESTED.exists() else {}
    dec = json.loads(DECISIONS.read_text()) if DECISIONS.exists() else {}
    n = 0
    for x in d["items"]:
        if x["status"] == "new" and x["id"] in sug:
            g = sug[x["id"]]
            x.update(status="skipped", by="editor") if g.get("skip") else x.update(status="suggested", reply=g["reply"])
            n += 1
        if x["status"] in ("new", "suggested") and x["id"] in dec:
            k = dec[x["id"]]
            x.update(status="approved" if k.get("status") == "approved" else "skipped",
                     reply=(k.get("reply") or x.get("reply") or "").strip(), decided=k.get("at"))
            n += 1
    return n


def _live_id(v) -> str:
    v = str(v or "")
    return "" if not v or v.startswith(("dry", "ERROR", "waiting")) else v


def _call(method: str, path: str, token: str, **params) -> dict:
    params["access_token"] = token
    r = requests.request(method, f"{GRAPH}/{path}", params=params if method == "GET" else None,
                         data=None if method == "GET" else params, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(r.json().get("error", {}).get("message", r.text)[:200])
    return r.json()


def worth_reply(text: str, likes: int) -> bool:
    """A comment worth a human answer: an opinion or a question, not just an emoji or 'congrats'."""
    t = (text or "").strip()
    return (len(t) >= 25 or likes >= 2 or "?" in t) and len(t.split()) >= 3


def candidate(platform: str, post: dict, c: dict) -> dict:
    return {"id": f"{platform}-{c['id']}", "platform": platform, "comment_id": c["id"], "post": post["id"],
            "post_title": post.get("title") or post.get("story") or "", "author": c.get("author", ""),
            "text": c.get("text", "")[:600], "likes": c.get("likes", 0), "created": c.get("created", ""),
            "status": "new"}


def run(now: datetime | None = None, folder: Path = q.QUEUE) -> dict:
    now = now or datetime.now(timezone.utc)
    rep = {"liked": 0, "first": 0, "new": 0, "sent": 0, "errors": []}
    if FILE.exists():
        d0 = load()
        if merge(d0):
            save(d0)
    if os.environ.get("LC_DRY_RUN", "1") != "0":
        rep["off"] = "testfase: er staan nog geen echte posts online"
        return rep
    from .meta import accounts
    try:
        a = accounts()
    except Exception as e:
        rep["off"] = str(e)
        return rep
    if not a.get("page_token"):
        rep["off"] = "geen Meta-sleutel"
        return rep
    d = load()
    merge(d)
    liked, known = set(d["liked"]), {x["id"] for x in d["items"]}
    since = (now - timedelta(days=DAYS)).isoformat()
    for p in q.load("posted", folder) + q.load("ready", folder):
        if (p.get("posted_at") or "") < since:
            continue
        res = p.get("results") or {}
        fb, ig = _live_id(res.get("facebook")), _live_id(res.get("instagram"))
        if fb:
            try:
                if fb not in d["first"]:
                    msg = FIRST_COMMENTS[sum(map(ord, p["id"])) % len(FIRST_COMMENTS)]
                    d["first"][fb] = _call("POST", f"{fb}/comments", a["page_token"], message=msg).get("id", "")
                    rep["first"] += 1
                cs = _call("GET", f"{fb}/comments", a["page_token"], filter="toplevel", limit=100,
                           fields="id,message,from{id,name},like_count,created_time").get("data", [])
                found = []
                for c in cs:
                    if (c.get("from") or {}).get("id") == a["page_id"]:
                        continue
                    if c["id"] not in liked and rep["liked"] < MAX_LIKES:
                        _call("POST", f"{c['id']}/likes", a["page_token"])
                        liked.add(c["id"])
                        d["liked"].append(c["id"])
                        rep["liked"] += 1
                    found.append({"id": c["id"], "text": c.get("message", ""), "author": (c.get("from") or {}).get("name", ""),
                                  "likes": c.get("like_count", 0), "created": c.get("created_time", "")})
                rep["new"] += _collect(d, known, "facebook", p, found)
            except Exception as e:
                rep["errors"].append(f"facebook {p['id']}: {e}")
        if ig and a.get("ig_token"):
            try:
                cs = _call("GET", f"{ig}/comments", a["ig_token"], limit=100,
                           fields="id,text,username,like_count,timestamp").get("data", [])
                found = [{"id": c["id"], "text": c.get("text", ""), "author": c.get("username", ""),
                          "likes": c.get("like_count", 0), "created": c.get("timestamp", "")}
                         for c in cs if c.get("username") != a.get("ig_username")]
                rep["new"] += _collect(d, known, "instagram", p, found)
            except Exception as e:
                rep["errors"].append(f"instagram {p['id']}: {e}")
    for x in d["items"]:
        if x.get("status") != "approved" or not (x.get("reply") or "").strip():
            continue
        try:
            if x["platform"] == "facebook":
                _call("POST", f"{x['comment_id']}/comments", a["page_token"], message=x["reply"].strip())
            else:
                _call("POST", f"{x['comment_id']}/replies", a["ig_token"], message=x["reply"].strip())
            x.update(status="sent", sent_at=now.isoformat())
            rep["sent"] += 1
        except Exception as e:
            x.update(status="error", error=str(e)[:200])
            rep["errors"].append(f"antwoord {x['id']}: {e}")
    save(d)
    return rep


def _collect(d: dict, known: set, platform: str, post: dict, found: list[dict]) -> int:
    good = sorted((c for c in found if worth_reply(c["text"], c["likes"])),
                  key=lambda c: (-c["likes"], -len(c["text"])))
    have = sum(1 for x in d["items"] if x["post"] == post["id"] and x["platform"] == platform)
    n = 0
    for c in good:
        if have + n >= PER_POST:
            break
        item = candidate(platform, post, c)
        if item["id"] in known:
            continue
        d["items"].append(item)
        known.add(item["id"])
        n += 1
    return n


def pending() -> list[dict]:
    """Reply suggestions waiting for Joshua (for the dashboard)."""
    return [x for x in load()["items"] if x.get("status") in ("suggested", "new")]


if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))

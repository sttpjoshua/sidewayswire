"""Plans every ready post per platform: score, which platform, when, caption, short version.

Runs in every run (after build, before publish). Rules:
- each platform has its own rhythm (platforms.RHYTHM); never more than its slots per day;
- reels are taken best score first, but never two from the same episode on one day per platform;
- Instagram only gets reels with a score of at least IG_MIN_SCORE, or the ones Joshua sent there;
- news and carousels go to Instagram and Facebook in the morning slot, oldest first; urgent kinds and
  Joshua's own time (want_at / pinned) keep their moment;
- what is planned within FREEZE_HOURS stays put (its media is already on the site);
- what does not fit in HORIZON_DAYS waits in stock ("voorraad", no time yet) instead of piling up on one day.

    python -m lc.planner          # plans and saves; prints a summary
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import handles, platforms
from . import queue as q

ROOT = Path(__file__).resolve().parent.parent
MOMENTS = ROOT / "data" / "podcasts" / "moments"
HORIZON_DAYS = 28
FREEZE_HOURS = 36
RECENT = 3                              # a driver comes back on the same platform after at least 3 other reels
REEL_KINDS = {"stream_clip", "podcast_clip", "battle_reel", "vlog_clip"}
URGENT = q.URGENT
FRESH_HOURS = 48                        # news is old after two days: it is skipped instead of posted late
FRESH_KINDS = {"news", "hook"}
KIND_POINTS = {"battle": 30, "final": 30, "crash": 28, "omt": 28, "qualify": 24, "call": 18, "moment": 16,
               "quote": 12, "fact": 8, "rumor": 8}


# ---------- score ----------
def moment_of(p: dict) -> dict:
    if p.get("kind") not in REEL_KINDS or not p.get("id", "").startswith("pod-"):
        return {}
    ep, _, i = p["id"][4:].rpartition("-")
    f = MOMENTS / f"{ep}.json"
    try:
        return json.loads(f.read_text())[int(i)]
    except Exception:
        return {}


def score(p: dict, m: dict, reg: dict) -> int:
    """0..100. Kind of moment, split battle, how well-known the drivers are, livestream footage, length."""
    s = KIND_POINTS.get(m.get("kind", ""), 10)
    s += 15 if p.get("format") == "split" or m.get("split") else 0
    s += {"stream_clip": 12, "vlog_clip": 8}.get(p.get("kind"), 0)
    prios = [r["prio"] for r in (handles.lookup(reg, n) for n in handles.people(m)) if r]
    s += {1: 25, 2: 14}.get(min(prios), 4) if prios else 0
    s += 5 if len(prios) >= 2 else 0
    length = float(m.get("end", 0)) - float(m.get("start", 0))
    s += 10 if 15 <= length <= 45 else 5 if length <= 70 else 0
    s += 3 if m.get("hook") else 0
    return max(0, min(100, s))


# ---------- calendar ----------
def _slots(platform: str, day, kind: str):
    for hm, use in platforms.RHYTHM[platform].items():
        if use == kind:
            h, mi = map(int, hm.split(":"))
            yield datetime(day.year, day.month, day.day, h, mi, tzinfo=q.TZ).astimezone(timezone.utc)


def active_platforms() -> list[str]:
    """In the test phase everything is planned; once live only connected channels are."""
    import os
    if os.environ.get("LC_DRY_RUN", "1") != "0":
        return list(platforms.RHYTHM)
    f = ROOT / "data" / "channels.json"
    con = {c["id"] for c in json.loads(f.read_text())["channels"] if c.get("connected")} if f.exists() else set()
    return [p for p in platforms.RHYTHM if p in con]


def plan(posts: list[dict], now: datetime | None = None) -> dict:
    now = max(now or datetime.now(timezone.utc), q.START.astimezone(timezone.utc))
    real_now = datetime.now(timezone.utc)
    freeze = real_now + timedelta(hours=FREEZE_HOURS)
    reg, plats = handles.registry(), active_platforms()
    expire(posts, real_now)
    todo = [p for p in posts if p.get("status") in ("ready", "approved")]
    taken = defaultdict(set)            # platform -> set of datetimes
    eps_on = defaultdict(set)           # (platform, date) -> episodes
    recent = defaultdict(list)          # platform -> people of the last reels
    last_q = {}                         # platform -> last day with an evergreen question post
    for p in todo:
        m = moment_of(p)
        p["_moment"] = m
        if m:
            p["score"] = score(p, m, reg)
            p["moment_kind"], p["people"] = m.get("kind"), handles.people(m)[:3]
        is_reel = p.get("kind") in REEL_KINDS or (p.get("media") or [""])[0].endswith(".mp4")
        p["_type"] = "reel" if is_reel else "post"
        want = [x for x in (p.get("platforms") or ["instagram", "facebook"]) if x in plats]
        if not is_reel:
            want = [x for x in want if x not in platforms.VIDEO_ONLY]
        if p.get("kind") == "vlog_clip":
            want = [x for x in want if x != "youtube"]
        p["platforms"] = p.get("platforms") or ["instagram", "facebook"]
        p["_want"] = want
        old = p.get("plan") or {}
        done = set((p.get("results") or {}).keys())
        p["plan"] = {}
        for pl in want:
            if pl in done:
                continue
            t = old.get(pl)
            fixed = (t and datetime.fromisoformat(t) <= freeze) or (p.get("pinned") and t)
            if fixed:
                p["plan"][pl] = t
                taken[pl].add(datetime.fromisoformat(t))
                eps_on[(pl, datetime.fromisoformat(t).astimezone(q.TZ).date())].add(p["id"].rpartition("-")[0])
    # Urgent posts and Joshua's own times: as soon as asked, on all their platforms.
    for p in todo:
        if p["_type"] == "post" and (p.get("kind") in URGENT or p.get("want_at") or p.get("pinned_at")):
            t = p.get("pinned_at") or p.get("want_at") or p.get("post_at")
            for pl in p["_want"]:
                if pl not in p["plan"] and t:
                    p["plan"][pl] = t
                    taken[pl].add(datetime.fromisoformat(t))
    # Image posts (news, kop-posts, carousels): oldest first; evergreen question posts only fill what is left,
    # and never two of them in a row on one platform (news and real stories come first).
    posts_ = sorted((p for p in todo if p["_type"] == "post" and not p["plan"]),
                    key=lambda p: (bool(p.get("evergreen")), p.get("created") or p.get("built") or ""))
    # Reels: best first; Joshua's choice for Instagram wins.
    reels = sorted((p for p in todo if p["_type"] == "reel"),
                   key=lambda p: (-(p.get("score") or 0), p.get("created") or ""))
    days = [now.astimezone(q.TZ).date() + timedelta(days=d) for d in range(HORIZON_DAYS)]
    for pl in plats:
        last_q[pl] = None
        queue_posts = [p for p in posts_ if pl in p["_want"] and pl not in p["plan"]]
        queue_reels = [p for p in reels if pl in p["_want"] and pl not in p["plan"]]
        if pl == "instagram":
            queue_reels = [p for p in queue_reels if p.get("ig") == "yes" or
                           (p.get("ig") != "no" and (p.get("score") or 0) >= platforms.IG_MIN_SCORE)]
            queue_reels.sort(key=lambda p: (p.get("ig") != "yes", -(p.get("score") or 0)))
        for day in days:
            for kind, pool in (("post", queue_posts), ("reel", queue_reels)):
                for t in _slots(pl, day, kind):
                    if t <= now or t in taken[pl]:
                        continue
                    # Variety: not the same episode twice a day, and not the same driver as in the last
                    # RECENT reels on this platform (falls back gracefully when the pool runs dry).
                    seen = set(sum(recent[pl][-RECENT:], []))
                    fresh = [p for p in pool if p["id"].rpartition("-")[0] not in eps_on[(pl, day)]]
                    pick = next((p for p in fresh if not seen & set(p.get("people") or [])), None) or \
                        (fresh[0] if fresh else None)
                    if pick is None:
                        pick = pool[0] if pool and kind == "post" else None
                    if pick is not None and kind == "post" and pick.get("evergreen") and last_q[pl] and (day - last_q[pl]).days < 2:
                        continue                    # a question day, then a day off: keeps them special
                    if pick is not None and kind == "post" and pick.get("evergreen"):
                        last_q[pl] = day
                    if pick is None:
                        continue
                    pool.remove(pick)
                    pick["plan"][pl] = t.isoformat()
                    if kind == "reel":
                        recent[pl].append(list(pick.get("people") or []))
                    taken[pl].add(t)
                    eps_on[(pl, day)].add(pick["id"].rpartition("-")[0])
    rep = defaultdict(int)
    for p in todo:
        times = sorted(p["plan"].values())
        p["post_at"] = times[0] if times else None
        p["status"] = "ready" if p.get("status") == "approved" and times else p["status"]
        if p["_type"] == "reel" or p.get("caption"):
            p["_moment"] = p.get("_moment") or {}
            p["captions"] = platforms.captions(p)
            p["collaborators"] = platforms.collaborators(p)
        rep["planned" if times else "voorraad"] += 1
        for pl in p["plan"]:
            rep[pl] += 1
        for k in ("_moment", "_type", "_want"):
            p.pop(k, None)
    return dict(rep)


def expire(posts: list[dict], now: datetime) -> list[dict]:
    """News that waited longer than FRESH_HOURS for a slot is skipped: posting it late makes the
    channel look slow. Kept: Joshua's own choices (approved, want_at, pinned), urgent kinds,
    evergreen posts and posts that already went out on one platform or are planned within the freeze."""
    out = []
    for p in posts:
        if p.get("status") != "ready" or p.get("kind") not in FRESH_KINDS or p.get("evergreen"):
            continue
        if p.get("want_at") or p.get("pinned_at") or p.get("pinned") or p.get("results"):
            continue
        born = p.get("created") or p.get("built")
        if not born:
            continue
        b = datetime.fromisoformat(born)
        b = b if b.tzinfo else b.replace(tzinfo=timezone.utc)
        if (now - b).total_seconds() < float(p.get("fresh_hours") or FRESH_HOURS) * 3600:
            continue
        soon = [datetime.fromisoformat(t) for t in (p.get("plan") or {}).values()]
        if any(now <= t <= now + timedelta(hours=FREEZE_HOURS) for t in soon) and now >= q.START:
            continue                        # already on the site and about to go out: let it go
        p.update(status="skipped", skip_reason=f"verouderd: ouder dan {FRESH_HOURS} uur", plan={}, post_at=None,
                 _expired=True)
        out.append(p)
    return out


def remaining(p: dict) -> list[str]:
    """Platforms this post should still go to (used by publish to decide when a post is done)."""
    plats = active_platforms()
    is_reel = p.get("kind") in REEL_KINDS or (p.get("media") or [""])[0].endswith(".mp4")
    want = [x for x in (p.get("platforms") or ["instagram", "facebook"]) if x in plats]
    if not is_reel:
        want = [x for x in want if x not in platforms.VIDEO_ONLY]
    elif "instagram" in want and p.get("ig") != "yes" and (p.get("ig") == "no" or (p.get("score") or 0) < platforms.IG_MIN_SCORE):
        want.remove("instagram")
    return [x for x in want if x not in (p.get("results") or {})]


def run() -> dict:
    posts = q.load()
    rep = plan(posts)
    for p in posts:
        if p.pop("_expired", False):
            rep["verouderd"] = rep.get("verouderd", 0) + 1
            q.save(p)
        elif p.get("status") in ("ready", "approved"):
            q.save(p)
    return rep


if __name__ == "__main__":
    print(json.dumps(run(), indent=1))

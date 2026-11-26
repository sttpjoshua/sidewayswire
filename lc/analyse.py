"""Analist (Joshua, 26 nov): the numbers behind the channel, every day, without credits.

Reads docs/stats.json (lc/stats.py fetches reach, likes, comments, shares per post and followers per day)
and the queue, and writes docs/agents/analist.json: what works per format, kind of moment, series, hour,
weekday and platform, the best and weakest posts, and follower growth. Groups with fewer than MIN_POSTS
measured posts are marked as too little data, so nobody draws conclusions from two posts.

The strateeg (Claude, every Monday morning) turns this into the plan for the week: data/strategy.json.

    python -m lc.analyse
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import agents
from . import queue as q

ROOT = Path(__file__).resolve().parent.parent
STATS = ROOT / "docs" / "stats.json"
MIN_POSTS = 5
DAYS = ["ma", "di", "wo", "do", "vr", "za", "zo"]


def _score(row: dict) -> tuple[float, dict]:
    ig, fb = row.get("instagram") or {}, row.get("facebook") or {}
    likes = (ig.get("likes") or 0) + (fb.get("reactions") or 0)
    comments = (ig.get("comments") or 0) + (fb.get("comments") or 0)
    shares = (ig.get("shares") or 0) + (fb.get("shares") or 0)
    reach = (ig.get("reach") or 0)
    return likes + 3 * comments + 5 * shares, {"likes": likes, "comments": comments, "shares": shares, "reach": reach}


def run(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    st = json.loads(STATS.read_text()) if STATS.exists() else {"days": {}, "posts": {}}
    queue = {p["id"]: p for p in q.load()}
    groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    rows = []
    for pid, row in (st.get("posts") or {}).items():
        if not (row.get("instagram") or row.get("facebook")):
            continue
        sc, parts = _score(row)
        p = queue.get(pid, {})
        try:
            t = datetime.fromisoformat(row["posted_at"]).astimezone(timezone(timedelta(hours=1)))
        except Exception:
            t = None
        keys = {"format": row.get("format") or "post", "soort": p.get("moment_kind") or p.get("kind") or "?",
                "serie": (p.get("series") or (p.get("credit") or "").lstrip("@") or "?"),
                "uur": f"{t.hour:02d}:00" if t else "?", "dag": DAYS[t.weekday()] if t else "?"}
        for g, k in keys.items():
            groups[g][k].append(sc)
        rows.append({"id": pid, "title": row.get("title"), "score": sc, **parts, **keys})
    table = {}
    for g, d in groups.items():
        table[g] = sorted(({"key": k, "posts": len(v), "gem": round(sum(v) / len(v), 1), "genoeg": len(v) >= MIN_POSTS}
                           for k, v in d.items()), key=lambda x: -x["gem"])
    rows.sort(key=lambda r: -r["score"])
    days = sorted((st.get("days") or {}).items())
    f_now = ((days[-1][1].get("instagram") or {}).get("followers") or 0) if days else 0
    week_ago = (now - timedelta(days=7)).date().isoformat()
    f_then = next(((d.get("instagram") or {}).get("followers") or 0 for day, d in days if day >= week_ago), f_now)
    report = {"gemeten_posts": len(rows), "volgers_instagram": f_now, "groei_7_dagen": f_now - f_then,
              "per": table, "beste": rows[:5], "zwakste": rows[-5:][::-1] if len(rows) > 5 else []}
    lines = []
    if len(rows) < MIN_POSTS:
        lines.append(f"Nog te weinig gemeten posts ({len(rows)}). Conclusies pas vanaf {MIN_POSTS} posts per groep; posten start 1 december.")
    else:
        for g in ("format", "soort", "uur"):
            ok = [x for x in table.get(g, []) if x["genoeg"]]
            if len(ok) >= 2:
                lines.append(f"Beste {g}: {ok[0]['key']} ({ok[0]['gem']} punten gem.), zwakste: {ok[-1]['key']} ({ok[-1]['gem']}).")
        if rows:
            lines.append(f"Beste post: {rows[0]['title']} ({rows[0]['score']} punten).")
    lines.append(f"Instagram: {f_now} volgers, {f_now - f_then:+d} in 7 dagen.")
    old = json.loads((agents.DOCS / "analist.json").read_text()) if (agents.DOCS / "analist.json").exists() else {}
    hist = []
    if old.get("summary") != lines:
        hist.append({"at": now.isoformat(), "text": lines[0][:160]})
    agents.report("analist", "wacht", None, hist, where="GitHub, elke dag", summary=lines, report=report,
                  counts={"gemeten posts": len(rows), "volgers": f_now})
    return {"posts": len(rows), "followers": f_now}


if __name__ == "__main__":
    print(run())

"""Mijlpalen om geld te verdienen: rekent uit waar het kanaal staat en welke mijlpalen gehaald zijn.

Leest data/milestones.json (definities), docs/stats.json (volgers), data/youtube/info.json, data/tiktok/info.json
en de geplaatste posts; houdt in data/milestones_state.json bij wanneer een mijlpaal gehaald is en welke acties
Joshua heeft afgevinkt (dat laatste doet het dashboard). Resultaat in docs/status.json onder "money".
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import rights

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "milestones_state.json"


def _j(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def metrics(posts: list[dict]) -> dict:
    st = _j(ROOT / "docs" / "stats.json", {})
    days = st.get("days", {})
    last = days[sorted(days)[-1]] if days else {}
    ig = (last.get("instagram") or {}).get("followers")
    fb = (last.get("facebook") or {}).get("followers")
    yt = last.get("youtube", {}).get("subscribers") or _j(ROOT / "data" / "youtube" / "info.json", {}).get("subscribers")
    tt = (last.get("tiktok") or {}).get("followers") or _j(ROOT / "data" / "tiktok" / "info.json", {}).get("follower_count")
    vals = [int(x) for x in (ig, fb, yt, tt) if x not in (None, "")]
    from .queue import START                         # test posts from before the start date do not count
    posted = sorted(p["posted_at"] for p in posts if p.get("status") == "posted" and p.get("posted_at")
                    and datetime.fromisoformat(p["posted_at"]) >= START)
    weeks = 0
    if posted:
        weeks = (datetime.now(timezone.utc) - datetime.fromisoformat(posted[0])).days // 7
    perms = rights.permitted()
    recent = [p for p in posts if p.get("status") in ("ready", "approved", "posted")]
    mix = {"eigen": 0, "toestemming": 0, "geleend": 0}
    for p in recent:
        mix[rights.rights_of(p, perms)["r"]] += 1
    return {"ig": ig, "fb": fb, "yt": int(yt) if yt not in (None, "") else None, "tt": tt, "total": sum(vals) if vals else 0,
            "weeks": weeks, "posted": len(posted), "mix": mix}


def build(posts: list[dict]) -> dict:
    defs = _j(ROOT / "data" / "milestones.json", {}).get("milestones", [])
    state = _j(STATE, {"reached": {}, "done": {}})
    m = metrics(posts)
    now = datetime.now(timezone.utc).isoformat()
    out, changed = [], False
    for d in defs:
        val = 1 if d["metric"] == "always" else m.get(d["metric"])
        ok = val is not None and val >= d["at"]
        if ok and d["id"] not in state["reached"]:
            state["reached"][d["id"]] = now
            changed = True
        done = state["done"].get(d["id"], {})
        out.append({**d, "value": val, "reached": state["reached"].get(d["id"]),
                    "pct": 100 if ok else (0 if not val or not d["at"] else min(99, int(val / d["at"] * 100))),
                    "open": [a["id"] for a in d["actions"] if a["id"] not in done] if ok else [],
                    "done": done})
    if changed:
        STATE.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n")
    perms = rights.permitted()
    return {"metrics": m, "milestones": out, "permissions": [
        {"key": k, "who": v["who"], "how": v["how"], "commercial": v["commercial"], "proof": v["proof"]} for k, v in perms.items()]}

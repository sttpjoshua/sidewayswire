"""Turns drafts in queue/ into finished images and gives them a posting time.

Runs every 15 minutes after the collector:
1. Picks up Joshua's Telegram answers (place / skip / block source).
2. Renders every draft. Images go to docs/media/<id>/ so GitHub Pages serves
   them on a public URL (Instagram needs a URL, not a file).
3. A post that does not fit, or that the editor marked check=true, goes to
   Telegram and waits. The rest gets a slot and status 'ready'.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import queue as q
from .render import Renderer
from .store import Store
from .telegram import Telegram

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "docs" / "media"
STATE = ROOT / "data" / "state.json"

# Kinds Joshua always sees first (from the plan): battle reels at the start,
# debate posts, and anything about a crash or injury.
ALWAYS_CHECK = {"debate", "crash"}   # Joshua (nov 2026): approve by default, only check what is really uncertain


def _state() -> dict:
    return json.loads(STATE.read_text()) if STATE.exists() else {"tg_offset": 0}


def apply_answers(tg: Telegram, store: Store | None, folder: Path = q.QUEUE) -> list:
    st = _state()
    answers, st["tg_offset"] = tg.answers(st.get("tg_offset", 0))
    by_id = {p["id"]: p for p in q.load(folder=folder)}
    for action, pid in answers:
        p = by_id.get(pid)
        if not p or p.get("status") != "check":
            continue
        if action == "ok":
            p["status"] = "ready"
            p["post_at"] = q.next_slot(list(by_id.values()), p["kind"]).isoformat()
        else:
            p["status"] = "skipped"
            if action == "block" and store and p.get("credit"):
                store.block(p["credit"], "blocked by Joshua via Telegram")
        q.save(p, folder)
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(st))
    return answers


def run(folder: Path = q.QUEUE, media: Path = MEDIA, tg: Telegram | None = None,
        store: Store | None = None) -> dict:
    tg = tg or Telegram()
    report = {"rendered": 0, "ready": 0, "check": 0, "answers": 0}
    if tg.on:
        report["answers"] = len(apply_answers(tg, store, folder))
    # Approved or skipped on the dashboard: give approved posts a time (Joshua's own, or the next free slot).
    for p in q.load("approved", folder):
        p["status"] = "ready"
        p["post_at"] = p.get("want_at") or q.next_slot(q.load(folder=folder), p["kind"]).isoformat()
        q.save(p, folder)
        report["ready"] += 1
    drafts = q.load("draft", folder)
    if not drafts:
        return report
    with Renderer() as r:
        for p in drafts:
            p["media"], p["problems"] = ([p["video"]] if p.get("video") else []), []
            for i, slide in enumerate(p.get("slides", []), 1):
                out = (media / p["id"] / f"{i}.png").resolve()
                res = r.render(slide["template"], slide["data"], out)
                p["media"].append(str(out.relative_to(ROOT)))
                p["problems"] += [f"slide {i}: '{x['text']}' past niet" for x in res.problems]
                report["rendered"] += 1
            reason = None
            if p["problems"]:
                reason = "; ".join(p["problems"][:3])
            elif p.get("check") or p["kind"] in ALWAYS_CHECK:
                reason = p.get("check_reason", "deze soort post check jij altijd eerst")
            elif store and store.is_blocked(p.get("credit")):
                p["status"] = "skipped"
                q.save(p, folder)
                continue
            if reason:
                p["status"] = "check"
                report["check"] += 1
                if tg.on:
                    tg.check(p, str(ROOT / p["media"][0]), reason)
            else:
                p["status"] = "ready"
                p["post_at"] = q.next_slot(q.load(folder=folder), p["kind"]).isoformat()
                report["ready"] += 1
            p["built"] = datetime.now(timezone.utc).isoformat()
            q.save(p, folder)
    return report


if __name__ == "__main__":
    print(json.dumps(run(store=Store(str(ROOT / "data" / "lc.db"))), indent=1))

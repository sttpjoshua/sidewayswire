"""Agents on the dashboard (Joshua, 26 nov): who works on Sideways Wire, what they do now, what they made.

Every agent writes docs/agents/<id>.json. The Mac editors write theirs themselves (tools/mac/local_editor.py);
the agents on GitHub use report() below. Joshua steers them from the dashboard, page AGENTS:
data/agents.json  {"agents": {"<id>": {"on": true, "note": "his instruction"}}}
data/tips.json    {"tips": [{"id", "url", "note", "series", "at", "status": "new" | "done", "result"}]}

Agents on GitHub:
  scout     news scout: scores every inbox story (lc/collect.py runs it), the news editor follows that order
  qc        quality control: checks every post before it is planned (clips and run rounds)
Planned / outside the repo:
  tags      tags researcher (weekly), analist (weekly), wachter (system watcher, every morning 08:41)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "agents"
CFG = ROOT / "data" / "agents.json"

NAMES = {"battle": "Battle-redacteur", "podcast": "Podcast-redacteur", "nieuws": "Nieuwsredacteur",
         "community": "Community-redacteur", "scout": "Nieuwsscout", "qc": "Kwaliteitscontrole",
         "tags": "Tags-onderzoeker", "analist": "Analist", "wachter": "Systeemwachter"}


def config(aid: str) -> dict:
    d = json.loads(CFG.read_text()) if CFG.exists() else {}
    c = d.get("agents", {}).get(aid, {})
    return {"on": c.get("on", True), "note": c.get("note", "")}


def report(aid: str, state: str, doing: str | None, history: list[dict] | None = None, where: str = "GitHub",
           **extra) -> dict:
    DOCS.mkdir(parents=True, exist_ok=True)
    f = DOCS / f"{aid}.json"
    old = json.loads(f.read_text()) if f.exists() else {}
    hist = (history or []) + old.get("history", [])
    body = {"id": aid, "name": NAMES[aid], "where": where, "state": state, "doing": doing,
            "updated": datetime.now(timezone.utc).isoformat(), "note": config(aid)["note"],
            "history": hist[:25]} | extra
    f.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n")
    return body


# ---------- news scout ----------
KINDS = [  # (label, points, pattern)
    ("uitslag", 30, r"\b(wins?|won|victory|champion(ship)?|podium|takes? (the )?(win|title)|clinch)"),
    ("transfer", 30, r"\b(joins?|signs?|signed|leaves?|leaving|departs?|switch(es)?|new team|retires?|retirement|moves? to)\b"),
    ("nieuwe auto", 22, r"\b(new (car|build|livery|chassis)|livery|reveal(ed|s)?|unveil(ed|s)?|debut)"),
    ("kalender", 18, r"\b(schedule|calendar|season|round|venue|finale|rules?|regulation)"),
    ("crash", 12, r"\b(crash|wreck|wall|contact|injur)"),
]
NOISE = r"\b(tickets?|merch|giveaway|discount|sale|podcast|subscribe|timetable|entry ?list|livestream|watch live|chapter|vlog)\b"
SERIES_PTS = {"FD": 10, "DM": 10, "FD + DM": 8, "D1GP": 4}


def scout(inbox_path: Path = ROOT / "data" / "inbox.json", now: datetime | None = None) -> dict:
    """Gives every story a score: kind of news, how many sources carry it, how fresh, which series.
    Joshua's instruction can push a series or a word up (e.g. 'meer Drift Masters')."""
    now = now or datetime.now(timezone.utc)
    cfg = config("scout")
    if not inbox_path.exists():
        return {}
    d = json.loads(inbox_path.read_text())
    note = cfg["note"].lower()
    hist, top = [], []
    for s in d.get("stories", []):
        t = " ".join([s.get("title", "")] + [i.get("title", "") for i in s.get("items", [])[:4]]).lower()
        pts, why = 0, []
        for label, p, pat in KINDS:
            if re.search(pat, t):
                pts += p
                why.append(label)
                break
        buzz = int(s.get("buzz") or 1)
        pts += min(30, (buzz - 1) * 8)
        if buzz > 1:
            why.append(f"{buzz} bronnen")
        pts += SERIES_PTS.get(str(s.get("series") or ""), 2)
        try:
            age_h = (now - datetime.fromisoformat(str(s.get("published")).replace("Z", "+00:00"))).total_seconds() / 3600
        except Exception:
            age_h = 24
        pts += max(0, 20 - int(age_h / 2))
        if re.search(NOISE, t):
            pts -= 25
            why.append("ruis")
        if re.search(r"[぀-ヿ一-鿿]", s.get("title", "")):
            pts -= 15
            why.append("Japans")
        if "drift masters" in note and "DM" in str(s.get("series")):
            pts += 12
        if ("formula drift" in note or "fd" in note.split()) and "FD" in str(s.get("series")):
            pts += 12
        skip = age_h > 48 or pts < 15
        s["scout"] = {"score": pts, "why": why, "skip": skip}
        if not skip:
            top.append((pts, s["title"]))
    inbox_path.write_text(json.dumps(d, indent=1, ensure_ascii=False))
    top.sort(reverse=True)
    old = json.loads((DOCS / "scout.json").read_text()) if (DOCS / "scout.json").exists() else {}
    seen = {h.get("text") for h in old.get("history", [])}
    for p, t in top[:5]:
        line = f"{p} punten: {t[:90]}"
        if line not in seen:
            hist.append({"at": now.isoformat(), "text": line})
    report("scout", "wacht", None, hist, top=[{"score": p, "title": t} for p, t in top[:8]],
           counts={"stories": len(d.get("stories", [])), "worth": len(top)})
    return {"worth": len(top)}


# ---------- quality control ----------
EM = "—"


def qc(folder: Path | None = None) -> dict:
    """Checks every post that is not posted yet. Hard problems stop a post (status check with the reason);
    small ones are only noted. Joshua then only sees what failed, not everything."""
    from . import queue as q
    from . import handles
    folder = folder or q.QUEUE
    reg = handles.registry()
    posts = q.load(folder=folder)
    seen_captions = {}
    stopped, warned, ok = [], 0, 0
    for p in posts:
        if p.get("status") not in ("draft", "ready", "approved", "check"):
            continue
        hard, soft = [], []
        kind = p.get("kind")
        clip = kind in ("podcast_clip", "stream_clip")
        if clip and not p.get("video"):
            hard.append("geen video")
        cap = p.get("caption") or ""
        if not cap.strip() and kind != "hook":
            hard.append("geen caption")
        if EM in cap or EM in json.dumps(p.get("captions") or {}, ensure_ascii=False):
            hard.append("lange streep in de tekst")
        sig = re.sub(r"\W+", "", cap.lower())[:120]
        if sig and sig in seen_captions:
            hard.append(f"dubbel met {seen_captions[sig]}")
        elif sig:
            seen_captions[sig] = p["id"]
        if len(cap) > 2100:
            soft.append("caption erg lang")
        if p.get("missing_handles"):
            soft.append("tags nog open: " + ", ".join(p["missing_handles"][:3]))
        if clip and p.get("sync_shift") and abs(p["sync_shift"]) > 1.5:
            soft.append(f"beeld liep {p['sync_shift']} s uit de pas (gecorrigeerd)")
        if p.get("skip_reason") == "geen beeld":
            hard.append("geen beeld")
        p_old = p.get("qc") or {}
        p["qc"] = {"hard": hard, "soft": soft, "at": datetime.now(timezone.utc).isoformat()}
        changed = p_old.get("hard") != hard or p_old.get("soft") != soft
        if hard and p.get("status") in ("draft", "ready", "approved"):
            p.update(status="check", check=True, check_reason="controle: " + ", ".join(hard))
            stopped.append(p["id"])
            changed = True
        elif soft:
            warned += 1
        else:
            ok += 1
        if changed:
            q.save(p, folder=folder)
    now = datetime.now(timezone.utc).isoformat()
    hist = [{"at": now, "text": f"tegengehouden: {i}", "ref": i} for i in stopped[:10]]
    counts = {"goed": ok, "opmerking": warned, "tegengehouden": len(stopped)}
    old = json.loads((DOCS / "qc.json").read_text()) if (DOCS / "qc.json").exists() else {}
    if old.get("counts") != counts:
        hist.append({"at": now, "text": f"ronde: {ok} goed, {warned} met opmerking, {len(stopped)} tegengehouden"})
    report("qc", "wacht", None, hist, counts=counts)
    return {"ok": ok, "warned": warned, "stopped": len(stopped)}


if __name__ == "__main__":
    import sys
    act = (sys.argv[1:] or ["qc"])[0]
    print({"scout": scout, "qc": qc}[act]())

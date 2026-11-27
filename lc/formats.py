"""Own formats (Joshua, 27 nov 2026): posts made entirely by us, so they may always earn money.

Runs every 15 minutes in run.yml and makes each post once (data/formats_state.json):

- Drift Kalender, Monday morning: the events of this week from data/calendar.json (kept up to date by
  the kalender agent every Sunday) as a carousel: a cover with every event in local time, then one slide
  per event with the session times in 12 cities around the world. A week without events: no post.
- Vraag van de week, Wednesday evening: the next unused question from data/questions.json.
- Antwoorden, Saturday: the most liked answers under Wednesday's question (Instagram and Facebook),
  with the user's name. Always checked by Joshua first, because it quotes other people.

The Weekly video (Sunday) is made in lc/weekly.py by the formats workflow.
New formats go to Joshua's check first; settings "formats_auto" lists the ones he lets go by themselves.

    python -m lc.formats            # what is due now
    python -m lc.formats calendar   # make one now (calendar | question | answers), for a test
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import queue as q
from . import timezones as tz

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "formats_state.json"
CALENDAR = ROOT / "data" / "calendar.json"
QUESTIONS = ROOT / "data" / "questions.json"
SETTINGS = ROOT / "data" / "settings.json"
NL = ZoneInfo("Europe/Amsterdam")
CITIES = tz.CITIES_A + tz.CITIES_B
TAGS = "#drift #drifting #formulad #driftmasters #sidewayswire"
# weekday (Mon=0), from this local hour, posting moment (local)
WHEN = {"calendar": (0, 6, "08:30"), "question": (2, 6, "20:30"), "answers": (5, 6, "12:30")}


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _state() -> dict:
    s = _json(STATE, {})
    s.setdefault("done", {})
    s.setdefault("questions_used", [])
    return s


def _save_state(s: dict):
    STATE.write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def week_id(d) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _check(fmt: str) -> bool:
    return fmt not in (_json(SETTINGS, {}).get("formats_auto") or [])


def _want(local_day, hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    return datetime(local_day.year, local_day.month, local_day.day, h, m, tzinfo=NL).astimezone(timezone.utc).isoformat()


def _post(pid: str, kind: str, title: str, slides: list, caption: str, check: bool, reason: str, want: str, **extra) -> dict:
    p = {"id": pid, "kind": kind, "story": title, "title": title, "slides": slides, "caption": caption,
         "platforms": ["instagram", "facebook"], "check": check, "check_reason": reason, "status": "draft",
         "created": datetime.now(timezone.utc).isoformat(), "by": "formats", "own_format": kind, "want_at": want}
    p.update(extra)
    q.save(p)
    return p


# ---------------------------------------------------------------- Drift Kalender
def _sessions(e: dict) -> list[dict]:
    out = []
    for s in e.get("sessions") or []:
        try:
            out.append({"name": s["name"].upper(), "at": tz.parse_session(s["local"], e["tz"])})
        except Exception:
            continue
    return sorted(out, key=lambda s: s["at"])


def events_in_week(monday_local, events: list[dict]) -> list[dict]:
    start = datetime(monday_local.year, monday_local.month, monday_local.day, tzinfo=NL)
    end = start + timedelta(days=7)
    out = []
    for e in events:
        ss = _sessions(e)
        if ss and any(start <= s["at"] < end for s in ss):
            out.append({**e, "_s": ss})
    return sorted(out, key=lambda e: e["_s"][0]["at"])


def calendar_slides(evs: list[dict], week: str) -> tuple[list, str]:
    cover = []
    for e in evs[:4]:
        first, last = e["_s"][0]["at"], e["_s"][-1]["at"]
        cover.append({"cap": f"{e['name']} ({e.get('series', '')}): {e['_s'][-1]['name'].lower()} {last.strftime('%a %H:%M')} local time",
                      "day": first.strftime("%a").upper(), "date": first.strftime("%d").lstrip("0"),
                      "name": e["name"].upper(), "series": e.get("series", "").upper(), "place": e.get("place", "").upper(),
                      "what": e["_s"][-1]["name"], "local": f"{last.strftime('%a').upper()} {last.strftime('%H:%M')}"})
    slides = [{"template": "cal_cover.html", "data": {"week": week.split("-W")[1].lstrip("0"), "events": cover}}]
    for e in evs[:5]:
        ss = e["_s"][-3:]
        rows = tz.zone_rows([{"at": s["at"]} for s in ss], CITIES, e["tz"])
        if not any(r["tag"] for r in rows):     # the venue's own time is always on the slide
            venue = tz.zone_rows([{"at": s["at"]} for s in ss], [(e.get("city", e.get("place", "VENUE")).upper(), e["tz"])], e["tz"])
            rows = venue + rows
        rows.sort(key=lambda r: 0 if r["tag"] else 1)
        days = []
        for s in e["_s"]:
            d = s["at"].strftime("%a %d").upper().replace(" 0", " ")
            if d not in days:
                days.append(d)
        slides.append({"template": "cal_event.html", "data": {
            "name": (e.get("short") or e["name"]).upper(), "badge": days[:2] if len(days) <= 2 else [days[0], days[-1]],
            "place": f"{e.get('series', '').upper()} · {e.get('place', '').upper()}".strip(" ·"),
            "sessions": [s["name"] for s in ss], "rows": rows, "row_h": 60 if len(rows) <= 12 else 54,
            "meta_left": (e.get("watch") or "").upper()}})
    lines = ["🗓️ " + c.pop("cap") for c in cover]
    cap = ("This week in drift 🔥\n\n" + "\n".join(lines) +
           "\n\nSwipe for the times in your city 👉 Which one are you watching?\n\n" + TAGS)
    return slides, cap


def make_calendar(now: datetime, force=False) -> str:
    local = now.astimezone(NL)
    monday = (local - timedelta(days=local.weekday())).date()
    wk = week_id(monday)
    evs = events_in_week(monday, _json(CALENDAR, {}).get("events", []))
    if not evs:
        return "skip: geen events deze week"
    slides, cap = calendar_slides(evs, wk)
    pid = f"{monday.isoformat()}-drift-calendar"
    _post(pid, "calendar", f"THIS WEEK IN DRIFT · WEEK {wk.split('-W')[1]}", slides, cap, _check("calendar"),
          "nieuw format Drift Kalender: check jij eerst (klopt elke tijd?)",
          now.isoformat() if force else _want(monday, WHEN["calendar"][2]), people=[])
    return pid


# ---------------------------------------------------------------- Vraag van de week
def qsize(text: str) -> int:
    n = len(text)
    return 150 if n <= 26 else 130 if n <= 40 else 118 if n <= 56 else 100


def make_question(now: datetime, st: dict, force=False) -> str:
    qs = _json(QUESTIONS, {}).get("questions", [])
    left = [x for x in qs if x not in st["questions_used"]] or qs
    if not left:
        return "skip: geen vragen"
    text = left[0]
    local = now.astimezone(NL).date()
    wk = week_id(local)
    pid = f"{local.isoformat()}-question-of-the-week"
    cap = (f"Question of the week: {text} 👇\n\nDrop your answer in the comments. The most liked answers "
           f"are in Saturday's post, with your name on it.\n\n{TAGS}")
    _post(pid, "question", "QUESTION OF THE WEEK", [{"template": "q_ask.html", "data": {
        "week": wk.split("-W")[1].lstrip("0"), "question": text.upper(), "qsize": qsize(text)}}], cap,
        _check("question"), "nieuw format Vraag van de week: check jij eerst",
        now.isoformat() if force else _want(local, WHEN["question"][2]), question=text, week=wk)
    st["questions_used"].append(text)
    return pid


def _clean_answer(text: str) -> str:
    t = re.sub(r"@\w[\w.]*", "", text.split("\n")[0])
    t = re.sub(r"[^\w\s'&+./-]", " ", t, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip(" .-")
    if len(t) > 26:
        t = t[:26].rsplit(" ", 1)[0] + "…"
    return t.upper()


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]", "", t.lower())


def top_answers(comments: list[dict], n: int = 5) -> list[dict]:
    """comments: {text, author, likes, platform}. Most liked first, one per answer."""
    out, seen = [], set()
    for c in sorted(comments, key=lambda c: -(c.get("likes") or 0)):
        a = _clean_answer(c.get("text") or "")
        k = _norm(a)
        if len(k) < 2 or any(k in s or s in k for s in seen):
            continue
        seen.add(k)
        who = c.get("author") or ""
        user = f"@{who}" if c.get("platform") == "instagram" else (who.split(" ")[0] + " on Facebook" if who else "")
        out.append({"text": a, "user": user, "likes": c.get("likes") or 0})
        if len(out) == n:
            break
    return out


def _comments(p: dict) -> list[dict]:
    from .engage import _call, _live_id
    from .meta import accounts
    a, res, out = accounts(), p.get("results") or {}, []
    fb, ig = _live_id(res.get("facebook")), _live_id(res.get("instagram"))
    if fb and a.get("page_token"):
        for c in _call("GET", f"{fb}/comments", a["page_token"], filter="toplevel", limit=100,
                       fields="message,from{id,name},like_count").get("data", []):
            if (c.get("from") or {}).get("id") != a.get("page_id"):
                out.append({"text": c.get("message", ""), "author": (c.get("from") or {}).get("name", ""),
                            "likes": c.get("like_count", 0), "platform": "facebook"})
    if ig and a.get("ig_token"):
        for c in _call("GET", f"{ig}/comments", a["ig_token"], limit=100, fields="text,username,like_count").get("data", []):
            if c.get("username") != a.get("ig_username"):
                out.append({"text": c.get("text", ""), "author": c.get("username", ""),
                            "likes": c.get("like_count", 0), "platform": "instagram"})
    return out


def make_answers(now: datetime, force=False, comments: list[dict] | None = None) -> str:
    local = now.astimezone(NL).date()
    wk = week_id(local)
    qp = [p for p in q.load() if p.get("kind") == "question" and p.get("week") == wk]
    if not qp:
        return "skip: geen vraag deze week"
    qp = qp[-1]
    if comments is None:
        if qp.get("status") != "posted":
            return "skip: de vraag staat nog niet online"
        try:
            comments = _comments(qp)
        except Exception as e:
            return f"skip: reacties niet te lezen ({str(e)[:120]})"
    ans = top_answers(comments)
    if len(ans) < 3:
        return f"skip: te weinig antwoorden ({len(ans)})"
    pid = f"{local.isoformat()}-question-answers"
    lines = "\n".join(f"{i}. {a['text'].title()} ({a['user']})" for i, a in enumerate(ans, 1))
    cap = (f"You answered: {qp['question']}\n\n{lines}\n\nAgree? New question on Wednesday 👀\n\n{TAGS}")
    _post(pid, "answers", "YOU ANSWERED", [{"template": "q_answers.html", "data": {
        "week": wk.split("-W")[1].lstrip("0"), "question": qp["question"].upper(), "answers": ans}}], cap,
        True, "antwoorden van volgers: kijk of alles netjes is (namen en tekst)",
        now.isoformat() if force else _want(local, WHEN["answers"][2]), question=qp["question"], week=wk)
    return pid


# ---------------------------------------------------------------- run
def run(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now < q.START - timedelta(days=1):
        return {"off": "nog geen posts voor 1 december"}
    st, rep, local = _state(), {}, now.astimezone(NL)
    for fmt, (wd, hour, _) in WHEN.items():
        key = f"{fmt}:{week_id(local.date())}"
        if local.weekday() != wd or local.hour < hour or key in st["done"]:
            continue
        try:
            r = (make_calendar(now) if fmt == "calendar" else make_question(now, st) if fmt == "question"
                 else make_answers(now))
        except Exception as e:
            r = f"fout: {str(e)[:160]}"
        rep[fmt] = r
        # answers retry until the evening: the question may still be gathering comments
        if not (fmt == "answers" and r.startswith("skip") and local.hour < 20) and not r.startswith("fout"):
            st["done"][key] = r
    try:
        from . import statformats
        rep.update(statformats.run(now, st))
    except Exception as e:
        rep["statformats"] = f"fout: {str(e)[:160]}"
    if rep:
        _save_state(st)
    return rep


if __name__ == "__main__":
    arg = (sys.argv[1:] or [""])[0]
    n = datetime.now(timezone.utc)
    if arg == "calendar":
        out = make_calendar(n, force=True)
    elif arg == "question":
        s = _state()
        out = make_question(n, s, force=True)
        _save_state(s)
    elif arg == "answers":
        out = make_answers(n, force=True)
    else:
        out = run(n)
    print(json.dumps(out, indent=1, ensure_ascii=False))

"""Own formats from the results database (Joshua, 27 nov 2026), see lc/resultsdb.py:

- Stand na een ronde: as soon as new points come in (lc.resultsdb.run calls make_standings), top 10
  with movement. Urgent: goes out at the first free moment.
- Driver Card: Tuesday and Friday 18:30, the next driver of the top 20 (DM and FD in turns), no photo.
- Head to head: Thursday 19:30, the two drivers most often in the news together this week (both in
  the database); none: no post.
- Wie wint?: two days before a round (from data/calendar.json), the 4 in the best form; after the round
  (make_standings) how our picks did. On TikTok as a draft with poll options for Joshua.
All go to Joshua's check first (settings formats_auto lets one go by itself).
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from itertools import combinations

from . import queue as q
from . import resultsdb as db
from .formats import NL, TAGS, _check, _json, _post, _want, week_id, CALENDAR, events_in_week

SERIES_TAGS = {"DM": "#driftmasters #dmgp #drifting #sidewayswire", "FD": "#formulad #formuladrift #drifting #sidewayswire"}
ORD = lambda n: f"{n}{'TH' if 10 <= n % 100 <= 20 else {1: 'ST', 2: 'ND', 3: 'RD'}.get(n % 10, 'TH')}" if n else "–"


def stats(x: dict) -> dict:
    rs = [r for r in x.get("rounds", []) if r.get("pos")]
    pos = [r["pos"] for r in rs]
    return {"rounds": len(rs), "wins": sum(p == 1 for p in pos), "podiums": sum(p <= 3 for p in pos),
            "top8": sum(p <= 8 for p in pos), "best": min(pos) if pos else None,
            "avg": round(sum(pos) / len(pos), 1) if pos else None}


def standings_before(d: dict, n: int) -> dict:
    """name -> position after the rounds before round n (for the arrows)."""
    pts = {x["name"]: sum(r.get("points") or 0 for r in x.get("rounds", []) if r["n"] < n) for x in d["drivers"]}
    order = sorted((k for k in pts if pts[k] > 0), key=lambda k: -pts[k])
    return {k: i for i, k in enumerate(order, 1)}


def round_name(d: dict, n: int) -> str:
    r = next((r for r in d.get("rounds", []) if r["n"] == n), {})
    return (r.get("country") or r.get("name") or f"Round {n}")


# ---------------------------------------------------------------- Stand na een ronde
def make_standings(d: dict, n: int, now: datetime) -> str:
    before = standings_before(d, n)
    top = [x for x in d["drivers"] if x.get("points")][:10]
    if len(top) < 5:
        return "skip: te weinig coureurs in de stand"
    rows = []
    for i, x in enumerate(top, 1):
        b = before.get(x["name"])
        rows.append({"name": x["name"].upper(), "points": x["points"],
                     "move": None if n == 1 or b is None else ("up" if b > i else "down" if b < i else "same")})
    last = max(r["n"] for x in d["drivers"] for r in x.get("rounds", []))
    final = n == last and n == len(d.get("rounds", [])) and n > 1
    winner = next((x for x in d["drivers"] for r in x.get("rounds", []) if r["n"] == n and r["pos"] == 1), None)
    mover = max(((before.get(x["name"], 99) - i, x["name"]) for i, x in enumerate(top, 1) if n > 1), default=(0, ""))
    lead, second = top[0], top[1]
    lines = [f"{d['series']} standings after round {n} ({round_name(d, n)}) 📊", ""]
    if winner:
        lines.append(f"🏆 Round winner: {winner['name']}")
    lines.append(f"👑 {'Champion' if final else 'Leader'}: {lead['name']}, {lead['points'] - second['points']} points clear of {second['name']}")
    if mover[0] >= 2:
        lines.append(f"📈 Biggest climber in the top 10: {mover[1]} (+{mover[0]})")
    lines += ["", "Who takes it from here? 👇", "", SERIES_TAGS.get(d["short"], TAGS)]
    note = "" if d.get("complete") else "TOP 16 PER ROUND · "
    slide = {"template": "standings.html", "data": {
        "badge": [d["short"], str(d["season"])], "title": "FINAL STANDINGS" if final else "STANDINGS",
        "subtitle": f"AFTER ROUND {n} · {round_name(d, n).upper()}", "marker": None, "rows": rows,
        "meta_left": f"{note}SOURCE {('DM.GP' if d['short'] == 'DM' else 'FORMULAD.COM')}", "meta_right": "@SIDEWAYSWIRE"}}
    pid = f"{now.astimezone(NL).date().isoformat()}-{d['short'].lower()}-standings-r{n}"
    p = _post(pid, "stand", f"{d['short']} STANDINGS AFTER ROUND {n}", [slide], "\n".join(lines), _check("stand"),
              "nieuw format Stand na een ronde: klopt de stand?", now.isoformat(), series=d["short"], round=n,
              people=[x["name"] for x in top[:3]])
    p.pop("want_at", None)          # urgent: the planner gives it the first free moment
    q.save(p)
    res = make_prediction_result(d, n, now)
    return pid + (f" + {res}" if res.startswith(str(now.year)) or "-" in res else "")


# ---------------------------------------------------------------- Driver Card
def card_order() -> list[tuple[str, str]]:
    """(series, name) of the top 20, DM and FD in turns."""
    lists = []
    for s in ("FD", "DM"):
        d = db.latest(s)
        lists.append([(s, x["name"]) for x in (d or {}).get("drivers", [])[:10] if x.get("points")])
    out = []
    for i in range(10):
        for l in lists:
            if i < len(l):
                out.append(l[i])
    return out


def card_data(d: dict, x: dict, nr: int) -> dict:
    s = stats(x)
    first, _, last = x["name"].partition(" ")
    strip = []
    for r in d.get("rounds", []) or [{"n": k} for k in range(1, 9)]:
        got = next((y for y in x.get("rounds", []) if y["n"] == r["n"]), None)
        strip.append({"n": r["n"], "pos": got["pos"] if got else None})
    return {"badge": [d["short"], str(d["season"])], "number": x.get("number") or "", "first": first.upper(),
            "last": (last or first).upper(), "sub": " · ".join(v for v in [x.get("nat") or "", (x.get("car") or "").upper()] if v),
            "tiles": [["CHAMPIONSHIP", ORD(x.get("pos"))], ["POINTS", x.get("points") or 0], ["WINS", s["wins"]],
                      ["PODIUMS", s["podiums"]], ["BEST FINISH", ORD(s["best"])], ["AVG FINISH", s["avg"] or "–"]],
            "strip": strip, "nr": nr, "partial": not d.get("complete")}


def make_card(now: datetime, st: dict, force_name: str | None = None) -> str:
    done = st.setdefault("cards_done", [])
    order = card_order()
    if force_name:
        order = [o for o in order if o[1] == force_name] or [(s, force_name) for s in ("FD", "DM")]
    pick = next((o for o in order if f"{o[0]}:{o[1]}" not in done), None)
    if not pick:
        return "skip: alle kaarten gemaakt"
    d = db.latest(pick[0])
    x = next((y for y in (d or {}).get("drivers", []) if y["name"] == pick[1]), None)
    if not x:
        return f"skip: {pick[1]} niet in de database"
    nr = len(done) + 1
    s = stats(x)
    cap = (f"Driver Card #{nr}: {x['name']} 🃏\n\n{d['series']} {d['season']}: {ORD(x.get('pos')).lower()} in the championship, "
           f"{x.get('points')} points, {s['wins']} win{'s' if s['wins'] != 1 else ''}, {s['podiums']} podium{'s' if s['podiums'] != 1 else ''}.\n\n"
           f"Collect them all. Who should be next? 👇\n\n{SERIES_TAGS.get(d['short'], TAGS)}")
    local = now.astimezone(NL).date()
    pid = f"{local.isoformat()}-driver-card-{re.sub(r'[^a-z0-9]+', '-', x['name'].lower()).strip('-')}"
    _post(pid, "card", f"DRIVER CARD #{nr} · {x['name'].upper()}", [{"template": "driver_card.html", "data": card_data(d, x, nr)}],
          cap, _check("card"), "nieuw format Driver Card: kloppen de cijfers?",
          now.isoformat() if force_name else _want(local, "18:30"), people=[x["name"]], series=d["short"])
    done.append(f"{pick[0]}:{pick[1]}")
    return pid


# ---------------------------------------------------------------- Head to head
def _all_drivers() -> dict:
    out = {}
    for s in ("FD", "DM"):
        d = db.latest(s)
        for x in (d or {}).get("drivers", []):
            if x.get("points"):
                out.setdefault(x["name"], (d, x))
    return out


def pair_of_week(now: datetime, known: dict) -> tuple[str, str] | None:
    since = now - timedelta(days=7)
    c = Counter()
    for p in q.load():
        try:
            if datetime.fromisoformat(p.get("created", "")) < since:
                continue
        except Exception:
            continue
        text = " ".join([p.get("title") or "", p.get("caption") or ""] + list(p.get("people") or []))
        names = sorted(n for n in known if n.lower() in text.lower())
        for a, b in combinations(names, 2):
            c[(a, b)] += 1
    best = [k for k, v in c.most_common() if v >= 2]
    return best[0] if best else None


def h2h_data(a, b) -> dict:
    (da, xa), (db_, xb) = a, b
    sa, sb = stats(xa), stats(xb)
    rows = [["CHAMPIONSHIP", ORD(xa.get("pos")), ORD(xb.get("pos"))], ["POINTS", xa.get("points"), xb.get("points")],
            ["WINS", sa["wins"], sb["wins"]], ["PODIUMS", sa["podiums"], sb["podiums"]],
            ["BEST FINISH", ORD(sa["best"]), ORD(sb["best"])], ["AVG FINISH", sa["avg"] or "–", sb["avg"] or "–"]]
    better = lambda i, va, vb: (0 if va == vb else (1 if (va < vb if i in (0, 4, 5) else va > vb) else 2))
    num = lambda v: float(re.sub(r"[^0-9.]", "", str(v)) or 999)
    marks = [better(i, num(r[1]), num(r[2])) for i, r in enumerate(rows)]
    same = da is db_
    ahead = None
    if same:
        ra = {r["n"]: r["pos"] for r in xa.get("rounds", [])}
        rb = {r["n"]: r["pos"] for r in xb.get("rounds", [])}
        both = [n for n in ra if n in rb]
        ahead = [sum(ra[n] < rb[n] for n in both), sum(rb[n] < ra[n] for n in both), len(both)]
    return {"badge": [da["short"] if same else "FD / DM", str(da["season"])], "a": xa["name"].upper(), "b": xb["name"].upper(),
            "a_sub": (xa.get("car") or "").upper(), "b_sub": (xb.get("car") or "").upper(), "rows": rows, "marks": marks, "ahead": ahead}


def make_h2h(now: datetime, pair: tuple[str, str] | None = None) -> str:
    known = _all_drivers()
    pair = pair or pair_of_week(now, known)
    if not pair or pair[0] not in known or pair[1] not in known:
        return "skip: geen duo in het nieuws deze week"
    data = h2h_data(known[pair[0]], known[pair[1]])
    a, b = known[pair[0]][1], known[pair[1]][1]
    extra = ""
    if data["ahead"]:
        extra = f"\nIn the {data['ahead'][2]} rounds they both scored, {a['name']} finished ahead {data['ahead'][0]} times, {b['name']} {data['ahead'][1]} times."
    cap = (f"Head to head: {a['name']} vs {b['name']} ⚔️\n\nThe numbers from their {known[pair[0]][0]['season']} season.{extra}\n\n"
           f"Who's the better driver? 👇\n\n{TAGS}")
    local = now.astimezone(NL).date()
    pid = f"{local.isoformat()}-head-to-head"
    _post(pid, "h2h", f"HEAD TO HEAD · {a['name'].upper()} VS {b['name'].upper()}", [{"template": "h2h.html", "data": data}],
          cap, _check("h2h"), "nieuw format Head to head: kloppen de cijfers?",
          _want(local, "19:30"), people=[a["name"], b["name"]])
    return pid


# ---------------------------------------------------------------- Wie wint?
def form(d: dict, x: dict, k: int = 3) -> tuple[float, list]:
    rs = sorted((r for r in x.get("rounds", []) if r.get("pos")), key=lambda r: r["n"])[-k:]
    return (sum(r.get("points") or 0 for r in rs) / len(rs) if rs else 0.0), [r["pos"] for r in rs]


def favourites(d: dict, n: int = 4) -> list[dict]:
    rows = []
    for x in d["drivers"]:
        f, last = form(d, x)
        if last:
            rows.append({"name": x["name"], "car": x.get("car") or "", "form": f, "last": last})
    rows.sort(key=lambda r: -r["form"])
    return rows[:n]


def next_round(series: str, now: datetime) -> dict | None:
    evs = _json(CALENDAR, {}).get("events", [])
    local = now.astimezone(NL).date()
    for wk in range(0, 2):
        monday = local - timedelta(days=local.weekday()) + timedelta(weeks=wk)
        for e in events_in_week(monday, evs):
            if series.lower() in (e.get("series") or "").lower().replace("formula drift", "fd").replace("drift masters", "dm"):
                return e
    return None


def make_prediction(now: datetime, st: dict, series: str, force=False) -> str:
    e = next_round(series, now)
    if not e:
        return "skip: geen ronde in de kalender"
    first = e["_s"][0]["at"]
    key = f"predict:{series}:{e.get('id') or e['name']}"
    if key in st["done"]:
        return "skip: al gemaakt"
    if not force and not (timedelta(days=1) < first - now <= timedelta(days=2, hours=12)):
        return "skip: nog niet"
    d = db.latest(series)
    if not d:
        return "skip: geen uitslagen"
    fav = favourites(d)
    if len(fav) < 3:
        return "skip: te weinig vorm-data"
    rows = [{"name": f["name"].upper(), "sub": f["car"].upper(), "last": " · ".join(ORD(p) for p in f["last"])} for f in fav]
    cap = (f"Who wins {e['name']}? 🤔\n\nOur 4 favourites on form (last 3 rounds):\n" +
           "\n".join(f"{i}. {f['name']} ({', '.join(ORD(p).lower() for p in f['last'])})" for i, f in enumerate(fav, 1)) +
           f"\n\nPick your winner in the comments 👇 We'll see on {first.strftime('%A')} who was right.\n\n{SERIES_TAGS.get(series, TAGS)}")
    local = now.astimezone(NL).date()
    pid = f"{local.isoformat()}-who-wins-{series.lower()}"
    _post(pid, "predict", f"WHO WINS · {(e.get('short') or e['name']).upper()}", [{"template": "predict.html", "data": {
        "badge": [series, str(first.year)], "event": (e.get("short") or e["name"]).upper(), "rows": rows}}], cap,
        _check("predict"), "nieuw format Wie wint?: kloppen de favorieten?", now.isoformat() if force else _want(local, "19:30"),
        series=series, picks=[f["name"] for f in fav], event=e.get("id") or e["name"],
        platforms=["instagram", "facebook", "tiktok"], tiktok_video=True, tiktok_draft=True,
        poll={"question": "Who wins?", "options": [f["name"] for f in fav]}, people=[f["name"] for f in fav])
    st["done"][key] = pid
    return pid


def make_prediction_result(d: dict, n: int, now: datetime) -> str:
    preds = [p for p in q.load() if p.get("kind") == "predict" and p.get("series") == d["short"] and not p.get("resolved")
             and datetime.fromisoformat(p["created"]) > now - timedelta(days=10)]
    if not preds:
        return "geen voorspelling"
    p = preds[-1]
    fin = {x["name"]: next((r["pos"] for r in x.get("rounds", []) if r["n"] == n), None) for x in d["drivers"]}
    winner = next((k for k, v in fin.items() if v == 1), "")
    rows = [{"name": name.upper(), "pos": fin.get(name), "hit": fin.get(name) == 1} for name in p.get("picks", [])]
    hit = any(r["hit"] for r in rows)
    cap = (f"How did our picks do? {'✅ We called it: ' + winner + ' wins!' if hit else '❌ Nobody saw ' + winner + ' coming.'}\n\n" +
           "\n".join(f"{r['name'].title()}: {ORD(r['pos']).lower() if r['pos'] else 'no result'}" for r in rows) +
           f"\n\nDid you pick right? 👇\n\n{SERIES_TAGS.get(d['short'], TAGS)}")
    pid = f"{now.astimezone(NL).date().isoformat()}-who-wins-{d['short'].lower()}-result"
    _post(pid, "predict_result", "OUR PICKS VS THE RESULT", [{"template": "predict.html", "data": {
        "badge": [d["short"], str(d["season"])], "event": round_name(d, n).upper(), "result": True, "winner": winner.upper(),
        "rows": [{"name": r["name"], "sub": "", "last": ORD(r["pos"]) if r["pos"] else "–", "hit": r["hit"]} for r in rows]}}],
        cap, _check("predict"), "nieuw format Wie wint? (uitslag)", now.isoformat(), series=d["short"], people=[winner])
    p["resolved"] = pid
    q.save(p)
    return pid


# ---------------------------------------------------------------- planning (called by lc.formats.run)
WHEN = {"card": [(1, 6), (4, 6)], "h2h": [(3, 6)]}


def run(now: datetime, st: dict) -> dict:
    local, rep = now.astimezone(NL), {}
    for fmt, slots in WHEN.items():
        for wd, hour in slots:
            key = f"{fmt}:{local.date().isoformat()}"
            if local.weekday() != wd or local.hour < hour or key in st["done"]:
                continue
            try:
                r = make_card(now, st) if fmt == "card" else make_h2h(now)
            except Exception as e:
                r = f"fout: {str(e)[:160]}"
            rep[fmt] = r
            if not r.startswith("fout"):
                st["done"][key] = r
    for s in ("DM", "FD"):
        try:
            r = make_prediction(now, st, s)
        except Exception as e:
            r = f"fout: {str(e)[:160]}"
        if not r.startswith("skip"):
            rep[f"predict-{s}"] = r
    return rep

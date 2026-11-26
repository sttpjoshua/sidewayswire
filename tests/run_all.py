"""Runs every proeftest in one go: python -m tests.run_all"""
import json, subprocess, sys
from pathlib import Path
from lc.render import Renderer
from lc.timezones import parse_session, zone_rows, CITIES_A, CITIES_B
from lc.video import battle_reel
from lc import collect, feeds

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"; OUT.mkdir(exist_ok=True)
ph = (ROOT / "tests/data/photo_test.jpg").as_uri()
fails = []

fd = json.loads((ROOT / "data/archive/2026/fd.json").read_text())
rows = [{"name": n.upper(), "points": p, "move": None} for n, p in fd["standings_final"][:10]]
ses = [{"name": "QUALI", "at": parse_session("2026-10-23 18:00", "America/Los_Angeles")},
       {"name": "TOP 32", "at": parse_session("2026-10-24 13:30", "America/Los_Angeles")},
       {"name": "GREAT 8", "at": parse_session("2026-10-24 16:00", "America/Los_Angeles")},
       {"name": "FINAL", "at": parse_session("2026-10-24 18:00", "America/Los_Angeles")}]
jobs = {
    "t_news": ("news.html", json.loads((ROOT / "tests/data/news.json").read_text())),
    "t_standings": ("standings.html", {"badge": ["FD", "2026"], "title": "FINAL STANDINGS", "subtitle": "FORMULA DRIFT PRO 2026",
                    "marker": "6 points in it!", "rows": rows, "meta_left": "SOURCE FORMULA DRIFT", "meta_right": "@sidewayswire"}),
    "t_zones_b": ("zones.html", {"badge": ["FD", "R8"], "heading2": "ASIA & OCEANIA", "marker": "set an alarm!",
                  "session_names": [s["name"] for s in ses], "rows": zone_rows(ses, CITIES_B),
                  "meta_left": "4 / 7 · TIMES ARE LOCAL, DST INCLUDED", "meta_right": "SWIPE →"}),
}
with Renderer() as r:
    for name, (tpl, data) in jobs.items():
        if tpl == "news.html":
            data["photo"] = ph
        res = r.render(tpl, data, OUT / f"{name}.png")
        print("render", name, res.ok)
        if not res.ok: fails.append(name)
    r.render("reel_split_overlay.html", {"w": 1080, "h": 1920, "bg": "transparent", "driver_a": "DEANE",
             "driver_b": "J. SHANAHAN", "credit": "@[source]"}, OUT / "reel_overlay.png", transparent=True)

rep = battle_reel(str(ROOT / "tests/clips/run1.mp4"), str(ROOT / "tests/clips/run2.mp4"),
                  str(OUT / "reel_overlay.png"), str(OUT / "battle_reel_test.mp4"), length=4.5)
ok = abs(rep["initiation_run1"] - 1.8) < 0.15 and abs(rep["initiation_run2"] - 3.1) < 0.15
print("battle reel sync", ok, rep)
if not ok: fails.append("sync")

W = [("Formula DRIFT", "FD", "fd", None), ("Drifted.com", "FD + DM", "drifted", None)]
m = {"fd": "tests/feeds/fd.xml", "drifted": "tests/feeds/drifted.xml"}
db = Path("/tmp/lc_test.db"); db.unlink(missing_ok=True)
from datetime import datetime, timezone
import re as _re
fx = lambda u: _re.sub(r"<pubDate>[^<]+</pubDate>", "<pubDate>" + datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000") + "</pubDate>", (ROOT / m[u]).read_text())
c = collect.run(ROOT / "tests/feeds/sources.csv", db, Path("/tmp/lc_inbox.json"), fetch=fx, watch=W)
ok = c["new_items"] == 3 and c["inbox"] == 2
print("collector", ok, {k: v for k, v in c.items() if k != "targets"})
if not ok: fails.append("collector")

import shutil, os
from datetime import datetime, timezone, timedelta
from lc import queue as q, build, publish
F = Path("/tmp/lc_queue"); shutil.rmtree(F, ignore_errors=True)
nd = json.loads((ROOT / "tests/data/news.json").read_text()) | {"photo": ph}
q.save({"id": "t-ok", "kind": "news", "status": "draft", "slides": [{"template": "news.html", "data": nd}], "caption": "x"}, F)
q.save({"id": "t-long", "kind": "news", "status": "draft", "slides": [{"template": "news.html",
        "data": nd | {"headline": ["THIS HEADLINE IS FAR TOO LONG TO EVER FIT ON ONE SINGLE TAPE BAR", "B"]}}], "caption": "x"}, F)
b = build.run(F, ROOT / "docs/media")
os.environ["LC_DRY_RUN"] = "1"
from lc import planner as _pl
_ps = q.load(folder=F); _pl.plan(_ps)                  # the real run plans between build and publish
for _p in _ps:
    q.save(_p, F)
pub = publish.run(F, now=max(datetime.now(timezone.utc), q.START.astimezone(timezone.utc)) + timedelta(days=3))  # nothing is planned before START
st = {x["id"]: x["status"] for x in q.load(folder=F)}
ok = st == {"t-ok": "posted", "t-long": "check"} and pub["dry_run"]
print("queue pipeline", ok, st)
if not ok: fails.append("pipeline")

from lc import planner
now = datetime.now(timezone.utc)
old = (now - timedelta(hours=60)).isoformat()
ex = [{"id": "n-old", "kind": "news", "status": "ready", "created": old},
      {"id": "n-new", "kind": "news", "status": "ready", "created": now.isoformat()},
      {"id": "n-mine", "kind": "news", "status": "ready", "created": old, "want_at": now.isoformat()},
      {"id": "c-old", "kind": "stream_clip", "status": "ready", "created": old}]
planner.expire(ex, now)
st = {x["id"]: x["status"] for x in ex}
ok = st == {"n-old": "skipped", "n-new": "ready", "n-mine": "ready", "c-old": "ready"}
print("old news expires", ok, st)
if not ok: fails.append("expire")

shutil.rmtree(ROOT / "docs/media/t-ok", ignore_errors=True); shutil.rmtree(ROOT / "docs/media/t-long", ignore_errors=True)
print("ALL OK" if not fails else f"FAILED: {fails}")
sys.exit(1 if fails else 0)

"""Own formats (Joshua, 27 nov 2026): calendar, question of the week, answers, Weekly."""
import datetime as dt

from lc import formats as f
from lc import weekly as w

EV = [{"series": "Formula DRIFT", "name": "Long Beach Showdown", "place": "Long Beach, USA", "city": "Long Beach",
       "tz": "America/Los_Angeles", "sessions": [{"name": "Top 32", "local": "2026-12-04 18:00"},
                                                 {"name": "Finals", "local": "2026-12-05 17:00"}]},
      {"series": "D1NZ", "name": "Gisborne", "place": "Gisborne, NZ", "tz": "Pacific/Auckland",
       "sessions": [{"name": "Finals", "local": "2026-12-14 16:00"}]}]


def test_calendar_week_and_world_times():
    evs = f.events_in_week(dt.date(2026, 11, 30), EV)
    assert [e["name"] for e in evs] == ["Long Beach Showdown"]
    slides, cap = f.calendar_slides(evs, "2026-W49")
    assert len(slides) == 2 and "Formula DRIFT" in cap
    rows = slides[1]["data"]["rows"]
    assert rows[0]["tag"] and len(rows) == 12
    ams = next(r for r in rows if r["city"].startswith("AMSTERDAM"))
    assert ams["cells"][1] == {"day": "SUN", "time": "02:00"}     # Sat 17:00 in Long Beach


def test_venue_row_added_when_not_a_listed_city():
    evs = f.events_in_week(dt.date(2026, 12, 14), EV)
    rows = f.calendar_slides(evs, "2026-W51")[0][1]["data"]["rows"]
    assert rows[0]["city"] == "GISBORNE, NZ" and len(rows) == 13


def test_top_answers_dedupe_and_names():
    a = f.top_answers([{"text": "AE86 all day 🔥", "author": "kid", "likes": 40, "platform": "instagram"},
                       {"text": "ae86!!", "author": "x", "likes": 3, "platform": "instagram"},
                       {"text": "S14", "author": "Pieter de Vries", "likes": 9, "platform": "facebook"}])
    assert [x["text"] for x in a] == ["AE86 ALL DAY", "S14"]
    assert a[0]["user"] == "@kid" and a[1]["user"] == "Pieter on Facebook"


def test_weekly_helpers():
    assert w.split_title("Conor Shanahan wins in Japan") == ["CONOR SHANAHAN", "WINS IN JAPAN"]
    assert w.series_of({"title": "x", "caption": "D1GP Round 10, the Formula DRIFT champ"}) == "D1GP"
    assert w.body_of("One. Two is here. #drift @x") == "One. Two is here."

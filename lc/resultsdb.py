"""Results database (Joshua, 27 nov 2026): official results per series and season, for the own formats
(standings after a round, Driver Cards, Head to head, Who wins?).

data/results/<series>-<year>.json:
  {"series": "Drift Masters", "short": "DM", "season": 2026, "source": "...", "fetched": ISO,
   "complete": true when every driver is in it (DM), false when only the top from official news (FD),
   "rounds": [{"n": 1, "name": "Vallelunga Circuit", "country": "Italy", "end": "2026-05-02"}],
   "drivers": [{"name": "Paweł Korpuliński", "number": 74, "nat": "POL", "car": "Nissan S14",
                "pos": 1, "points": 509, "wildcard": false, "rounds": [{"n": 1, "pos": 4, "points": 64}]}]}

Sources (Joshua has permission from Drift Masters):
- Drift Masters: the standings data that dm.gp's own standings page loads (season id in
  data/results/sources.json). Fetched on GitHub (dm.gp is not reachable from Claude's sessions):
  every 3 hours in the days around a round, else once a week.
- Formula DRIFT: formulad.com blocks automatic fetching, so the file is filled from FD's official news
  (news.formulad.com) by the kalender agent after each round; "complete": false.

    python -m lc.resultsdb            # fetch what is due (run.yml)
    python -m lc.resultsdb fetch dm   # fetch now
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR = ROOT / "data" / "results"
SOURCES = DIR / "sources.json"
DM_API = "https://dm.gp/umbraco/api/v1/seasons/{sid}/standings/drivers"
UA = {"User-Agent": "SidewaysWire/1.0 (+https://sttpjoshua.github.io/sidewayswire/; Drift Masters results with permission)"}


def _json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def path_for(short: str, year: int) -> Path:
    return DIR / f"{short.lower()}-{year}.json"


def load(short: str, year: int) -> dict | None:
    return _json(path_for(short, year), None)


def save(d: dict):
    DIR.mkdir(parents=True, exist_ok=True)
    path_for(d["short"], d["season"]).write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def latest(short: str) -> dict | None:
    """The newest season file of a series that has at least one round with points."""
    for p in sorted(DIR.glob(f"{short.lower()}-*.json"), reverse=True):
        d = _json(p, None)
        if d and done_rounds(d):
            return d
    return None


def nice_name(full: str) -> str:
    """'Paweł KORPULIŃSKI' -> 'Paweł Korpuliński' (DM writes surnames in capitals)."""
    out = []
    for w in full.split():
        out.append("-".join(x[:1].upper() + x[1:].lower() for x in w.split("-")) if w.isupper() and len(w) > 1 else w)
    return " ".join(out)


def _register() -> dict:
    """lowercase name -> name as written in the driver register (data/sources.csv), e.g. 'Duane McKeever'."""
    import csv
    try:
        with open(ROOT / "data" / "sources.csv", encoding="utf-8") as f:
            return {r["Naam"].strip().lower(): r["Naam"].strip() for r in csv.DictReader(f) if r.get("Naam")}
    except Exception:
        return {}


def _num(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def done_rounds(d: dict) -> list[int]:
    return sorted({r["n"] for x in d.get("drivers", []) for r in x.get("rounds", []) if r.get("points") is not None and r.get("pos")})


def from_dm(raw: list[dict], meta: dict, year: int) -> dict:
    drivers, reg = [], _register()
    for x in raw:
        name = nice_name(x.get("fullName", ""))
        drivers.append({"name": reg.get(name.lower(), name), "number": x.get("startingNumber"), "nat": x.get("nationality"),
                        "car": x.get("carName"), "pos": x.get("position"), "points": _num(x.get("totalPoints")),
                        "wildcard": bool(x.get("isWildcard")),
                        "rounds": sorted(({"n": r["roundNumber"], "pos": r.get("position"), "points": _num(r.get("points"))}
                                          for r in x.get("roundsResults") or [] if r.get("position")), key=lambda r: r["n"])})
    drivers.sort(key=lambda x: (x["pos"] or 999))
    return {"series": "Drift Masters", "short": "DM", "season": year, "source": "dm.gp (official standings)",
            "fetched": datetime.now(timezone.utc).isoformat(), "complete": True,
            "rounds": meta.get("rounds", []), "drivers": drivers}


def fetch_dm(year: int) -> dict:
    import requests
    meta = (_json(SOURCES, {}).get("dm") or {}).get(str(year)) or {}
    if not meta.get("season_id"):
        raise RuntimeError(f"geen season_id voor Drift Masters {year} in data/results/sources.json")
    r = requests.get(DM_API.format(sid=meta["season_id"]), headers=UA, timeout=30)
    r.raise_for_status()
    d = from_dm(r.json(), meta, year)
    if not d["drivers"]:
        raise RuntimeError("Drift Masters gaf een lege stand")
    return d


def changed(old: dict | None, new: dict) -> list[int]:
    """Rounds that are new in this fetch (points appeared)."""
    return [n for n in done_rounds(new) if n not in (done_rounds(old) if old else [])]


def _due(meta: dict, last: str | None, now: datetime) -> bool:
    if not last:
        return True
    age = now - datetime.fromisoformat(last)
    today = now.date()
    for r in meta.get("rounds", []):
        try:
            end = date.fromisoformat(r["end"])
        except Exception:
            continue
        if end - timedelta(days=1) <= today <= end + timedelta(days=3):
            return age > timedelta(hours=3)
    return age > timedelta(days=7)


def run(now: datetime | None = None, force: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    rep = {}
    for year, meta in ((_json(SOURCES, {}).get("dm") or {})).items():
        y = int(year)
        if y < now.year - 1:
            continue
        old = load("DM", y)
        if not force and not _due(meta, (old or {}).get("fetched"), now):
            continue
        try:
            new = fetch_dm(y)
        except Exception as e:
            rep[f"dm-{y}"] = f"fout: {str(e)[:160]}"
            continue
        fresh = changed(old, new)
        save(new)
        rep[f"dm-{y}"] = {"rondes": done_rounds(new), "nieuw": fresh}
        if fresh and old is not None:           # a round came in: the standings post (lc/formats)
            from . import formats
            rep[f"dm-{y}-post"] = formats.make_standings(new, fresh[-1], now)
    return rep


if __name__ == "__main__":
    args = sys.argv[1:]
    print(json.dumps(run(force=bool(args and args[0] == "fetch")), indent=1, ensure_ascii=False, default=str))

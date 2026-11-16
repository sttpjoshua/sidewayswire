"""Source list: the Bronnen sheet, exported as data/sources.csv.

The sheet stays the place where Joshua edits sources. A scheduled Claude task
copies it to data/sources.csv in the repo (the sheet itself is not reachable
from GitHub). Columns follow the sheet: Naam, Type, Serie, Prioriteit,
Instagram, YouTube / website, Land, Nr, Team / auto, Status, Notitie.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

# How often each priority is checked, in minutes.
CHECK_EVERY = {1: 15, 2: 60, 3: 24 * 60}


@dataclass
class Source:
    name: str
    kind: str          # Serie, Media, Sponsor, Coureur, Team, Fotograaf
    series: str        # FD, DM, FD + DM, D1GP, Drift Kings, NDC, Gatebil
    priority: int
    instagram: str | None
    web: str | None
    country: str | None
    number: str | None
    team: str | None
    status: str
    note: str | None

    @property
    def check_every_minutes(self) -> int:
        return CHECK_EVERY.get(self.priority, 60)

    @property
    def ig_username(self) -> str | None:
        return self.instagram.lstrip("@").strip() if self.instagram else None


def _clean(v):
    v = (v or "").strip()
    return v or None


def load(path: str | Path) -> list[Source]:
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            prio = row.get("Prioriteit") or "2"
            out.append(Source(
                name=row["Naam"].strip(), kind=_clean(row.get("Type")) or "Coureur",
                series=_clean(row.get("Serie")) or "", priority=int(float(prio)),
                instagram=_clean(row.get("Instagram")), web=_clean(row.get("YouTube / website")),
                country=_clean(row.get("Land")), number=_clean(row.get("Nr")),
                team=_clean(row.get("Team / auto")), status=_clean(row.get("Status")) or "Te zoeken",
                note=_clean(row.get("Notitie")),
            ))
    return out


def due(sources: list[Source], minutes_since_last: dict[str, float]) -> list[Source]:
    """Sources whose check interval has passed. Unknown sources are always due."""
    return [s for s in sources if minutes_since_last.get(s.name, 1e9) >= s.check_every_minutes]

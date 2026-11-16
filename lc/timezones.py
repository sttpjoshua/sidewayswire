"""Time zone conversion for livestream posts.

All session times are stored once, in the venue's own time zone. This module
converts them to the 12 cities on the livestream carousel, including daylight
saving time on the exact date (Europe and the US switch on different days).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

CITIES_A = [  # slide 3: Americas and Europe
    ("LOS ANGELES", "America/Los_Angeles"),
    ("CHICAGO", "America/Chicago"),
    ("NEW YORK", "America/New_York"),
    ("SÃO PAULO", "America/Sao_Paulo"),
    ("LONDON · DUBLIN", "Europe/London"),
    ("AMSTERDAM · WARSAW", "Europe/Amsterdam"),
]
CITIES_B = [  # slide 4: Middle East, Asia and Oceania
    ("HELSINKI · RIGA", "Europe/Helsinki"),
    ("DUBAI", "Asia/Dubai"),
    ("INDIA", "Asia/Kolkata"),
    ("BANGKOK · JAKARTA", "Asia/Bangkok"),
    ("TOKYO", "Asia/Tokyo"),
    ("SYDNEY", "Australia/Sydney"),
]


def parse_session(local: str, tz: str) -> datetime:
    """'2026-10-23 21:00' in the venue's zone -> aware datetime."""
    return datetime.strptime(local, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(tz))


def zone_label(tz: str, moments: list[datetime]) -> str:
    """Abbreviation, showing a change like 'BST→GMT' when DST flips during the event."""
    names = []
    for m in moments:
        n = m.astimezone(ZoneInfo(tz)).strftime("%Z")
        n = f"UTC{n}" if n[:1] in "+-" else n
        if n not in names:
            names.append(n)
    return "→".join(names)


def zone_rows(sessions: list[dict], cities: list[tuple[str, str]], venue_tz: str | None = None) -> list[dict]:
    """Rows for the 'your time' slides: one row per city, one cell per session."""
    moments = [s["at"] for s in sessions]
    rows = []
    for city, tz in cities:
        cells = []
        for m in moments:
            t = m.astimezone(ZoneInfo(tz))
            cells.append({"day": t.strftime("%a").upper(), "time": t.strftime("%H:%M")})
        rows.append({"city": city, "zone": zone_label(tz, moments),
                     "tag": "VENUE TIME" if tz == venue_tz else "", "cells": cells})
    return rows


def cover_times(first: datetime) -> list[dict]:
    """The three big start times on the livestream cover."""
    out = []
    for city, tz in [("LOS ANGELES", "America/Los_Angeles"), ("NEW YORK", "America/New_York"),
                     ("AMSTERDAM", "Europe/Amsterdam")]:
        t = first.astimezone(ZoneInfo(tz))
        out.append({"city": city, "time": f"{t.strftime('%a').upper()} {t.strftime('%H:%M')}"})
    return out

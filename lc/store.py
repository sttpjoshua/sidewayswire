"""Small SQLite store for everything the collector finds.

Items from different sources that describe the same story are grouped:
the same link, or a very similar title within 48 hours. The number of
sources in a group is the 'buzz' the editor uses to rank news.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  source TEXT, series TEXT, kind TEXT,
  title TEXT, url TEXT, media_url TEXT, media_type TEXT,
  published TEXT, found TEXT,
  story TEXT,
  raw TEXT
);
CREATE INDEX IF NOT EXISTS items_story ON items(story);
CREATE INDEX IF NOT EXISTS items_published ON items(published);
CREATE TABLE IF NOT EXISTS stories (
  id TEXT PRIMARY KEY, title TEXT, series TEXT, first_seen TEXT,
  buzz INTEGER DEFAULT 1, status TEXT DEFAULT 'new'   -- new, used, skipped
);
CREATE TABLE IF NOT EXISTS checks (source TEXT PRIMARY KEY, last TEXT);
CREATE TABLE IF NOT EXISTS blocklist (account TEXT PRIMARY KEY, reason TEXT, added TEXT);
"""

STOP = {"the", "a", "an", "in", "at", "of", "to", "for", "and", "on", "with", "is", "his", "her"}


def norm_title(t: str) -> str:
    t = re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())
    return " ".join(w for w in t.split() if w not in STOP)


def similar(a: str, b: str) -> float:
    na, nb = norm_title(a), norm_title(b)
    # Titles in Japanese (or other scripts) lose almost everything in norm_title:
    # compare the original text then.
    if len(na) < 0.5 * len(a or "") or len(nb) < 0.5 * len(b or ""):
        na, nb = (a or "").lower(), (b or "").lower()
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


class Store:
    def __init__(self, path: str = "data/lc.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def add(self, *, source: str, series: str, kind: str, title: str, url: str,
            published: datetime, media_url: str | None = None, media_type: str | None = None,
            raw: dict | None = None) -> tuple[str, bool]:
        """Add an item. Returns (story_id, is_new_item)."""
        item_id = hashlib.sha1((url or title).encode()).hexdigest()[:16]
        if self.db.execute("SELECT 1 FROM items WHERE id=?", (item_id,)).fetchone():
            return self.db.execute("SELECT story FROM items WHERE id=?", (item_id,)).fetchone()[0], False
        story = self._match_story(title, published, source) or item_id
        now = datetime.now(timezone.utc).isoformat()
        self.db.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, source, series, kind, title, url, media_url, media_type,
             published.isoformat(), now, story, json.dumps(raw or {})),
        )
        if story == item_id:
            self.db.execute("INSERT INTO stories(id,title,series,first_seen) VALUES (?,?,?,?)",
                            (story, title, series, now))
        else:
            self.db.execute(
                "UPDATE stories SET buzz=(SELECT COUNT(DISTINCT source) FROM items WHERE story=?) WHERE id=?",
                (story, story))
        self.db.commit()
        return story, True

    def _match_story(self, title: str, published: datetime, source: str = "") -> str | None:
        """Same story = a similar title from ANOTHER source within 48 hours.
        Two posts from one source are never merged (e.g. 'RD9 results' and 'RD10 results')."""
        since = (published - timedelta(hours=48)).isoformat()
        best, best_score = None, 0.0
        for row in self.db.execute("SELECT story, title FROM items WHERE published >= ? AND source != ?",
                                   (since, source)):
            s = similar(title, row["title"])
            if s > best_score:
                best, best_score = row["story"], s
        return best if best_score >= 0.72 else None

    def new_stories(self, limit: int = 50):
        return self.db.execute(
            "SELECT * FROM stories WHERE status='new' ORDER BY buzz DESC, first_seen DESC LIMIT ?",
            (limit,)).fetchall()

    def story_items(self, story: str):
        return self.db.execute("SELECT * FROM items WHERE story=? ORDER BY published", (story,)).fetchall()

    def mark(self, story: str, status: str):
        self.db.execute("UPDATE stories SET status=? WHERE id=?", (status, story))
        self.db.commit()

    def block(self, account: str, reason: str):
        """'Niet meer delen' list, filled from the Telegram takedown button."""
        self.db.execute("INSERT OR REPLACE INTO blocklist VALUES (?,?,?)",
                        (account.lower().lstrip("@"), reason, datetime.now(timezone.utc).isoformat()))
        self.db.commit()

    def is_blocked(self, account: str | None) -> bool:
        if not account:
            return False
        return bool(self.db.execute("SELECT 1 FROM blocklist WHERE account=?",
                                    (account.lower().lstrip("@"),)).fetchone())

    def touch(self, source: str):
        self.db.execute("INSERT OR REPLACE INTO checks VALUES (?,?)",
                        (source, datetime.now(timezone.utc).isoformat()))
        self.db.commit()

    def minutes_since_checks(self) -> dict[str, float]:
        now = datetime.now(timezone.utc)
        return {r["source"]: (now - datetime.fromisoformat(r["last"])).total_seconds() / 60
                for r in self.db.execute("SELECT * FROM checks")}

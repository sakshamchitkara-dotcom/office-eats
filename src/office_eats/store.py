"""Persistent team data in SQLite: lunch polls and votes (teams and rotation history live here too).

Kept apart from the API cache so `office-eats clear-cache` never wipes votes.
"""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("OFFICE_EATS_DB", Path.home() / ".local" / "share" / "office-eats" / "data.sqlite3"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS polls (id TEXT PRIMARY KEY, title TEXT NOT NULL, options TEXT NOT NULL,
                                  created REAL NOT NULL, closed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS votes (poll_id TEXT NOT NULL REFERENCES polls(id), voter TEXT NOT NULL,
                                  choice INTEGER NOT NULL, at REAL NOT NULL, PRIMARY KEY (poll_id, voter));
"""


class StoreError(ValueError):
    pass


class Store:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)  # the Slack server votes from worker threads
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)

    # --- polls -------------------------------------------------------------------------------------------------
    def create_poll(self, title: str, options: list[dict]) -> str:
        if not 2 <= len(options) <= 10:
            raise StoreError("a poll needs 2-10 options")
        poll_id = secrets.token_urlsafe(6)
        with self.lock, self.db:
            self.db.execute("INSERT INTO polls (id, title, options, created) VALUES (?, ?, ?, ?)",
                            (poll_id, title, json.dumps(options), time.time()))
        return poll_id

    def poll(self, poll_id: str) -> dict:
        row = self.db.execute("SELECT title, options, closed FROM polls WHERE id = ?", (poll_id,)).fetchone()
        if not row:
            raise StoreError(f"no poll {poll_id!r}")
        return {"id": poll_id, "title": row[0], "options": json.loads(row[1]), "closed": bool(row[2])}

    def vote(self, poll_id: str, voter: str, choice: int) -> None:
        """One vote per voter; voting again changes the vote."""
        p = self.poll(poll_id)
        if p["closed"]:
            raise StoreError("this poll is closed")
        if not 0 <= choice < len(p["options"]):
            raise StoreError(f"choice must be 1-{len(p['options'])}")
        if not voter.strip():
            raise StoreError("voter name required")
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO votes VALUES (?, ?, ?, ?)", (poll_id, voter.strip()[:80], choice, time.time()))

    def tally(self, poll_id: str) -> tuple[dict, list[tuple[dict, list[str]]]]:
        """(poll, [(option, [voters])]) sorted by votes, ties kept in the ranker's original order."""
        p = self.poll(poll_id)
        voters: list[list[str]] = [[] for _ in p["options"]]
        for voter, choice in self.db.execute("SELECT voter, choice FROM votes WHERE poll_id = ? ORDER BY at", (poll_id,)):
            voters[choice].append(voter)
        order = sorted(range(len(voters)), key=lambda i: -len(voters[i]))
        return p, [(p["options"][i], voters[i]) for i in order]

    def close_poll(self, poll_id: str) -> None:
        self.poll(poll_id)
        with self.lock, self.db:
            self.db.execute("UPDATE polls SET closed = 1 WHERE id = ?", (poll_id,))

"""Persistent team data in SQLite: lunch polls and votes, team profiles, weekly rotation picks.

Kept apart from the API cache so `office-eats clear-cache` never wipes votes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

# expanduser: a value copied from .env.example ("~/...") must not create a literal "~" directory.
DEFAULT_PATH = Path(os.environ.get("OFFICE_EATS_DB", Path.home() / ".local" / "share" / "office-eats" / "data.sqlite3")).expanduser()

SCHEMA = """
CREATE TABLE IF NOT EXISTS polls (id TEXT PRIMARY KEY, title TEXT NOT NULL, options TEXT NOT NULL,
                                  created REAL NOT NULL, closed INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS votes (poll_id TEXT NOT NULL REFERENCES polls(id), voter TEXT NOT NULL,
                                  choice INTEGER NOT NULL, at REAL NOT NULL, PRIMARY KEY (poll_id, voter));
CREATE TABLE IF NOT EXISTS teams (name TEXT PRIMARY KEY, location TEXT NOT NULL, office_name TEXT,
                                  diets TEXT NOT NULL DEFAULT '[]', party INTEGER NOT NULL DEFAULT 0, tz TEXT);
"""
CREATE_PICKS = """CREATE TABLE IF NOT EXISTS picks (team TEXT NOT NULL, week TEXT NOT NULL, venue_id TEXT NOT NULL,
                                              venue_name TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (team, week))"""
CREATE_MEMBERS = """CREATE TABLE IF NOT EXISTS members (team TEXT NOT NULL, name TEXT NOT NULL, diets TEXT NOT NULL DEFAULT '[]',
                                                  PRIMARY KEY (team, name))"""
CREATE_FEEDBACK = """CREATE TABLE IF NOT EXISTS feedback (team TEXT NOT NULL, week TEXT NOT NULL, venue_id TEXT NOT NULL,
                                                    voter TEXT NOT NULL, vote INTEGER NOT NULL, at REAL NOT NULL,
                                                    PRIMARY KEY (team, week, voter))"""
TEAM_FIELDS = ("location", "office_name", "diets", "party", "tz")


class StoreError(ValueError):
    pass


class Store:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)  # the Slack server votes from worker threads
        self.lock = threading.Lock()
        self.db.executescript(SCHEMA)
        self.db.execute(CREATE_PICKS)
        self.db.execute(CREATE_MEMBERS)
        self.db.execute(CREATE_FEEDBACK)
        if "invite_key" not in {r[1] for r in self.db.execute("PRAGMA table_info(polls)")}:  # added in 0.4
            self.db.execute("ALTER TABLE polls ADD COLUMN invite_key TEXT")

    # --- polls -------------------------------------------------------------------------------------------------
    def create_poll(self, title: str, options: list[dict]) -> str:
        if not 2 <= len(options) <= 10:
            raise StoreError("a poll needs 2-10 options")
        poll_id = secrets.token_hex(4)  # hex: never starts with "-", which argparse would read as a flag
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

    # --- signed per-voter links for the web page -----------------------------------------------------------
    def invite_token(self, poll_id: str, voter: str) -> str:
        """Token for voter's personal link. The first call gives the poll a secret key, which makes the web page
        invite-only: from then on it only accepts votes that carry a valid token, under the name the token was made for."""
        self.poll(poll_id)
        with self.lock, self.db:
            self.db.execute("UPDATE polls SET invite_key = ? WHERE id = ? AND invite_key IS NULL", (secrets.token_hex(16), poll_id))
        return self._token(poll_id, voter.strip()[:80])

    def invite_only(self, poll_id: str) -> bool:
        return self._key(poll_id) is not None

    def check_token(self, poll_id: str, voter: str, token: str) -> bool:
        return self._key(poll_id) is not None and hmac.compare_digest(self._token(poll_id, voter.strip()[:80]), token)

    def _key(self, poll_id: str) -> str | None:
        row = self.db.execute("SELECT invite_key FROM polls WHERE id = ?", (poll_id,)).fetchone()
        return row[0] if row else None

    def _token(self, poll_id: str, voter: str) -> str:
        key = self._key(poll_id)
        return hmac.new(key.encode(), f"{poll_id}:{voter}".encode(), hashlib.sha256).hexdigest()[:32]

    def close_poll(self, poll_id: str) -> None:
        self.poll(poll_id)
        with self.lock, self.db:
            self.db.execute("UPDATE polls SET closed = 1 WHERE id = ?", (poll_id,))

    # --- teams -------------------------------------------------------------------------------------------------
    def set_team(self, name: str, **fields) -> dict:
        """Create or update a team; fields left as None keep their stored value. diets is a set of diet names."""
        if bad := set(fields) - set(TEAM_FIELDS):
            raise StoreError(f"unknown team field(s) {sorted(bad)}")
        try:
            team = self.team(name)
        except StoreError:
            if not fields.get("location"):
                raise StoreError(f"new team {name!r} needs an office location") from None
            team = {"name": name, "location": "", "office_name": None, "diets": [], "party": 0, "tz": None}
        team.update({k: v for k, v in fields.items() if v is not None})
        team["diets"] = sorted(team["diets"])
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO teams VALUES (?, ?, ?, ?, ?, ?)",
                            (name, team["location"], team["office_name"], json.dumps(team["diets"]), team["party"], team["tz"]))
        return team

    def team(self, name: str) -> dict:
        row = self.db.execute("SELECT location, office_name, diets, party, tz FROM teams WHERE name = ?", (name,)).fetchone()
        if not row:
            raise StoreError(f"no team {name!r}; create it with: office-eats team set {name!r} --office ADDRESS")
        return {"name": name, "location": row[0], "office_name": row[1], "diets": json.loads(row[2]), "party": row[3], "tz": row[4]}

    def teams(self) -> list[dict]:
        return [self.team(n) for (n,) in self.db.execute("SELECT name FROM teams ORDER BY name")]

    # --- members: per-person dietary needs --------------------------------------------------------------------
    def set_member(self, team: str, name: str, diets: set[str]) -> dict:
        self.team(team)  # must exist
        if not name.strip():
            raise StoreError("member name required")
        member = {"name": name.strip()[:80], "diets": sorted(diets)}
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO members VALUES (?, ?, ?)", (team, member["name"], json.dumps(member["diets"])))
        return member

    def remove_member(self, team: str, name: str) -> None:
        with self.lock, self.db:
            if not self.db.execute("DELETE FROM members WHERE team = ? AND name = ?", (team, name)).rowcount:
                raise StoreError(f"team {team!r} has no member {name!r}")

    def members(self, team: str) -> list[dict]:
        rows = self.db.execute("SELECT name, diets FROM members WHERE team = ? ORDER BY name", (team,))
        return [{"name": n, "diets": json.loads(d)} for n, d in rows]

    # --- rotation ----------------------------------------------------------------------------------------------
    def record_pick(self, team: str, week: str, venue_id: str, venue_name: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO picks VALUES (?, ?, ?, ?, ?)", (team, week, venue_id, venue_name, time.time()))

    def picks(self, team: str, limit: int = 52) -> list[dict]:
        """Newest week first. Week keys are ISO weeks like 2026-W39, which sort correctly as text."""
        rows = self.db.execute("SELECT week, venue_id, venue_name FROM picks WHERE team = ? ORDER BY week DESC LIMIT ?", (team, limit))
        return [{"week": w, "venue_id": vid, "venue_name": name} for w, vid, name in rows]

    # --- feedback after lunch ----------------------------------------------------------------------------------
    def rate(self, team: str, voter: str, vote: int, week: str | None = None) -> dict:
        """Thumbs up (+1) or down (-1) on a rotation pick, the latest one by default. Rating again changes it."""
        if vote not in (1, -1):
            raise StoreError("vote must be +1 or -1")
        if not voter.strip():
            raise StoreError("voter name required")
        picks = self.picks(team)
        pick = next((p for p in picks if week in (None, p["week"])), None)
        if pick is None:
            raise StoreError(f"team {team!r} has no pick{' for ' + week if week else ''} to rate yet")
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO feedback VALUES (?, ?, ?, ?, ?, ?)",
                            (team, pick["week"], pick["venue_id"], voter.strip()[:80], vote, time.time()))
        return pick

    def feedback(self, team: str) -> dict[str, tuple[int, int]]:
        """venue_id -> (thumbs up, thumbs down) across every week the team ate there."""
        rows = self.db.execute("SELECT venue_id, SUM(vote > 0), SUM(vote < 0) FROM feedback WHERE team = ? GROUP BY venue_id", (team,))
        return {vid: (up, down) for vid, up, down in rows}

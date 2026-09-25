"""Tiny sqlite key/value cache with TTL, so repeat runs don't hit public APIs."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

DEFAULT_PATH = Path(os.environ.get("OFFICE_EATS_CACHE", Path.home() / ".cache" / "office-eats" / "cache.sqlite3"))


class Cache:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, expires REAL NOT NULL)")

    @staticmethod
    def key(*parts: object) -> str:
        return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()

    def get(self, key: str):
        row = self.db.execute("SELECT v, expires FROM kv WHERE k = ?", (key,)).fetchone()
        if not row or row[1] < time.time():
            return None
        return json.loads(row[0])

    def set(self, key: str, value, ttl: float) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO kv VALUES (?, ?, ?)", (key, json.dumps(value), time.time() + ttl))

    def clear(self) -> int:
        with self.db:
            return self.db.execute("DELETE FROM kv").rowcount

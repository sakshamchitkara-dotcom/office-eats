"""Polite HTTP: identifying User-Agent, per-host rate limit, sqlite caching."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.parse
import urllib.request

from . import __version__
from .cache import Cache

AUTH_HEADERS = {"authorization", "x-goog-api-key"}
DEFAULT_UA = f"office-eats/{__version__} (+https://github.com/sakshamchitkara-dotcom/office-eats)"


def user_agent() -> str:
    return os.environ.get("OFFICE_EATS_USER_AGENT") or DEFAULT_UA


class HttpError(RuntimeError):
    pass


class Http:
    """GET/POST JSON with caching and a minimum interval between calls to the same host."""

    def __init__(self, cache: Cache | None = None, min_interval: dict[str, float] | None = None, timeout: float = 60):
        self.cache = cache
        # Nominatim policy: max 1 req/s. Overpass: be gentle too.
        self.min_interval = {"nominatim.openstreetmap.org": 1.1, "overpass-api.de": 2.0, **(min_interval or {})}
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _wait(self, host: str) -> None:
        gap = self.min_interval.get(host, 0.0)
        with self._lock:  # ponytail: global lock, fine for a CLI; per-host locks if this ever runs concurrently
            delay = self._last.get(host, 0.0) + gap - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._last[host] = time.monotonic()

    def fetch(self, url: str, *, data: dict | None = None, json_body: dict | None = None,
              headers: dict | None = None, ttl: float = 86400, parse_json: bool = True):
        # Auth headers stay out of the cache key: rotating an API key should not bust the cache.
        safe_headers = {k: v for k, v in (headers or {}).items() if k.lower() not in AUTH_HEADERS}
        key = Cache.key(url, data, json_body, sorted(safe_headers.items()))
        if self.cache and ttl > 0 and (hit := self.cache.get(key)) is not None:
            return hit
        host = urllib.parse.urlsplit(url).hostname or ""
        self._wait(host)
        headers = {"User-Agent": user_agent(), **(headers or {})}
        body = None
        if json_body is not None:
            body = json.dumps(json_body).encode()
            headers["Content-Type"] = "application/json"
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except OSError as e:  # URLError/HTTPError/timeouts are all OSError subclasses
            raise HttpError(f"{host}: {e}") from e
        value = json.loads(raw) if parse_json else raw
        if self.cache and ttl > 0:
            self.cache.set(key, value, ttl)
        return value

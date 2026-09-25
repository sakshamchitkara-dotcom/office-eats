"""Office time zone from coordinates, so opening hours are checked in the office's local time.

Order: explicit --tz, then the optional offline `timezonefinder` package (pip install 'office-eats[tz]'),
then the `timezone` tag on the OSM boundaries containing the point (one Overpass is_in query, cached 90 days).
If all of that fails we return None and times stay naive, which is the pre-0.2 behaviour.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .http import Http, HttpError
from .overpass import OVERPASS

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _zone(name: str | None) -> ZoneInfo | None:
    try:
        return ZoneInfo(name) if name else None
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _timezonefinder(lat: float, lon: float) -> str | None:
    try:
        from timezonefinder import TimezoneFinder
    except ImportError:
        return None
    return TimezoneFinder().timezone_at(lat=lat, lng=lon)


def _osm(lat: float, lon: float, http: Http) -> str | None:
    q = f'[out:json][timeout:25];is_in({lat:.5f},{lon:.5f})->.a;area.a["timezone"];out tags;'
    data = http.fetch(OVERPASS, data={"data": q}, ttl=90 * 86400)
    # Smallest area wins: a city's tag is more specific than its country's.
    areas = sorted(data.get("elements", []), key=lambda e: -int(e.get("tags", {}).get("admin_level", "0") or 0))
    return next((name for e in areas if _zone(name := e["tags"].get("timezone"))), None)


def office_tz(lat: float, lon: float, http: Http | None = None, override: str | None = None) -> ZoneInfo | None:
    if override:
        if not (z := _zone(override)):
            raise ValueError(f"unknown time zone {override!r} (use an IANA name like Europe/London)")
        return z
    if z := _zone(_timezonefinder(lat, lon)):
        return z
    if http is not None:
        try:
            if z := _zone(_osm(lat, lon, http)):
                return z
        except (HttpError, ValueError, KeyError) as e:
            print(f"office-eats: time zone lookup failed ({e})", file=sys.stderr)
    return None


def to_office_time(when: datetime, zone: ZoneInfo | None) -> datetime:
    """Aware datetimes (ISO with an offset) become naive office-local; naive ones already are office-local."""
    if when.tzinfo is None:
        return when
    return (when.astimezone(zone) if zone else when.astimezone()).replace(tzinfo=None)


def parse_when(text: str | None, now: datetime | None = None) -> datetime | None:
    """'now', ISO ('2026-09-22 12:30'), or '<day> HH:MM' (next occurrence, e.g. 'fri 19:00')."""
    if not text:
        return None
    now = now or datetime.now()
    t = text.strip().lower()
    if t == "now":
        return now.replace(second=0, microsecond=0)
    parts = t.split()
    try:
        if len(parts) == 2 and parts[0][:3] in DAY_NAMES:
            hh, mm = map(int, parts[1].split(":"))
            ahead = (DAY_NAMES.index(parts[0][:3]) - now.weekday()) % 7
            when = (now + timedelta(days=ahead)).replace(hour=hh, minute=mm, second=0, microsecond=0)
            return when if when >= now else when + timedelta(days=7)
        return datetime.fromisoformat(text.strip())
    except ValueError:
        raise ValueError(f"can't read time {text!r}; use 'now', 'fri 19:00' or '2026-10-01 12:30'") from None

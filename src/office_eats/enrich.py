"""Derive cuisine, dietary options, distance and open-now from raw provider data."""
from __future__ import annotations

from datetime import datetime

from . import hours
from .models import Place, Venue, haversine_m, walk_minutes

DIETS = ("vegan", "vegetarian", "halal", "kosher", "gluten_free")
# Cuisines that strongly imply a dietary option even without an explicit diet:* tag.
CUISINE_DIETS = {"vegan": {"vegan", "vegetarian"}, "vegetarian": {"vegetarian"}, "halal": {"halal"},
                 "kosher": {"kosher"}, "falafel": {"vegetarian"}, "indian": {"vegetarian"}}


def cuisines(tags: dict[str, str]) -> list[str]:
    raw = tags.get("cuisine", "")
    return [c.strip().lower() for c in raw.replace(",", ";").split(";") if c.strip()]


def diets(tags: dict[str, str], cuisine: list[str]) -> set[str]:
    out = {d for d in DIETS if tags.get(f"diet:{d}") in ("yes", "only")}
    for c in cuisine:
        out |= CUISINE_DIETS.get(c, set())
    if "vegan" in out:
        out.add("vegetarian")
    return out


def enrich(venues: list[Venue], origin: Place, when: datetime | None = None) -> list[Venue]:
    for v in venues:
        if not v.cuisine:
            v.cuisine = cuisines(v.tags)
        v.diets |= diets(v.tags, v.cuisine)
        v.menu_url = v.menu_url or v.tags.get("website:menu")
        v.distance_m = haversine_m(origin.lat, origin.lon, v.lat, v.lon)
        v.walk_min = walk_minutes(v.distance_m)
        if when is not None:
            v.open_now = hours.is_open(v.opening_hours, when)
    return venues

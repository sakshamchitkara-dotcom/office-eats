"""Core data types and geo helpers."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

WALK_M_PER_MIN = 80.0  # ~4.8 km/h


@dataclass
class Place:
    """A geocoded office location."""

    name: str
    lat: float
    lon: float
    address: str = ""


@dataclass
class Venue:
    """A place to eat, normalised across providers."""

    id: str
    name: str
    lat: float
    lon: float
    kind: str = "restaurant"  # restaurant, cafe, fast_food, ...
    cuisine: list[str] = field(default_factory=list)
    diets: set[str] = field(default_factory=set)  # vegan, vegetarian, halal, kosher, gluten_free
    opening_hours: str | None = None
    website: str | None = None
    phone: str | None = None
    address: str | None = None
    price_level: int | None = None  # 1 ($) .. 4 ($$$$)
    rating: float | None = None  # 0..5 when a provider supplies one
    tags: dict[str, str] = field(default_factory=dict)
    source: str = "osm"
    # filled in by enrichment
    distance_m: float = 0.0
    walk_min: float = 0.0
    open_now: bool | None = None
    group_size: int = 0
    menu_url: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["diets"] = sorted(self.diets)
        return d


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def walk_minutes(distance_m: float) -> float:
    # ponytail: straight-line * 1.3 detour factor; swap for a routing engine (OSRM) if accuracy matters
    return distance_m * 1.3 / WALK_M_PER_MIN


def osm_link(v: Venue) -> str:
    kind, _, num = v.id.partition("/")
    if v.source == "osm" and kind in {"node", "way", "relation"}:
        return f"https://www.openstreetmap.org/{kind}/{num}"
    return f"https://www.openstreetmap.org/?mlat={v.lat:.6f}&mlon={v.lon:.6f}#map=19/{v.lat:.6f}/{v.lon:.6f}"

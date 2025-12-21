"""End-to-end pipeline: geocode -> fetch -> enrich -> rank -> (menu links, blurbs)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from .enrich import enrich
from .geocode import geocode
from .http import Http
from .models import WALK_M_PER_MIN, Place
from .providers import get_provider
from .scoring import PROFILES, Scored, rank
from .websites import add_menu_links

DEFAULT_RADIUS = {"lunch": 800, "coffee": 600, "dinner": 1500, "catering": 3000}


@dataclass
class Query:
    location: str  # address, company name, or "lat,lon"
    name: str | None = None
    use_case: str = "lunch"
    radius_m: int | None = None
    max_walk: float | None = None
    diets: set[str] = field(default_factory=set)
    party: int = 0
    when: datetime | None = None
    open_only: bool = False
    limit: int = 8
    provider: str = "osm"
    menus: bool = False

    def radius(self) -> int:
        if self.radius_m:
            return self.radius_m
        if self.max_walk:
            return int(self.max_walk * WALK_M_PER_MIN / 1.3)
        return DEFAULT_RADIUS[self.use_case]


@dataclass
class Result:
    query: Query
    place: Place
    items: list[Scored]
    candidates: int
    blurb_source: str = "deterministic"

    def to_dict(self) -> dict:
        q = asdict(self.query)
        q["diets"] = sorted(self.query.diets)
        q["when"] = self.query.when.isoformat() if self.query.when else None
        return {"query": q, "use_case_label": PROFILES[self.query.use_case].label, "place": asdict(self.place),
                "candidates": self.candidates, "blurb_source": self.blurb_source,
                "recommendations": [s.to_dict() for s in self.items]}


def recommend(q: Query, http: Http) -> Result:
    if q.use_case not in PROFILES:
        raise ValueError(f"use case must be one of {sorted(PROFILES)}")
    place = geocode(q.location, http, name=q.name)
    venues = get_provider(q.provider, http).nearby(place.lat, place.lon, q.radius())
    enrich(venues, place, q.when)
    items = rank(venues, q.use_case, diets=q.diets, party=q.party, open_only=q.open_only,
                 max_walk=q.max_walk, limit=q.limit)
    if q.menus:
        add_menu_links([s.venue for s in items], http)
    return Result(q, place, items, candidates=len(venues))

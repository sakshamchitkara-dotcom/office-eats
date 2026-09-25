"""End-to-end pipeline: geocode -> fetch -> enrich -> rank -> (menu links, blurbs)."""
from __future__ import annotations

import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .blurbs import MODEL, apply_deterministic, claude_shortlist
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
    llm: str = "auto"  # auto (use Claude if ANTHROPIC_API_KEY is set) | on | off

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


def recommend(q: Query, http: Http, llm_client=None) -> Result:
    if q.use_case not in PROFILES:
        raise ValueError(f"use case must be one of {sorted(PROFILES)}")
    place = geocode(q.location, http, name=q.name)
    venues = get_provider(q.provider, http).nearby(place.lat, place.lon, q.radius())
    enrich(venues, place, q.when)
    use_llm = q.llm == "on" or (q.llm == "auto" and bool(os.environ.get("ANTHROPIC_API_KEY")))
    # Give Claude a wider pool to choose from; the deterministic path just takes the top N.
    pool = rank(venues, q.use_case, diets=q.diets, party=q.party, open_only=q.open_only,
                max_walk=q.max_walk, limit=min(q.limit * 2, 20) if use_llm else q.limit)
    items, source = pool[: q.limit], "deterministic"
    if use_llm and pool:
        request = {"use_case": PROFILES[q.use_case].label, "party": q.party or None, "diets": sorted(q.diets),
                   "when": q.when.isoformat(timespec="minutes") if q.when else None, "office": place.name}
        try:
            items, source = claude_shortlist(pool, request, q.limit, client=llm_client), f"claude ({MODEL})"
        except Exception as e:  # any failure (no SDK, auth, network, refusal, bad JSON) -> deterministic
            print(f"office-eats: Claude unavailable, using deterministic blurbs ({type(e).__name__}: {e})", file=sys.stderr)
            items = pool[: q.limit]
    if source == "deterministic":
        apply_deterministic(items, q.use_case)
    if q.menus:
        add_menu_links([s.venue for s in items], http)
    return Result(q, place, items, candidates=len(venues), blurb_source=source)

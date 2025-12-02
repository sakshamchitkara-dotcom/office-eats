"""Use-case scoring: quick team lunch, client dinner, catering, coffee meeting."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import Venue


@dataclass(frozen=True)
class Profile:
    name: str
    label: str
    kinds: dict[str, float]  # amenity -> fit 0..1
    walk_scale_min: float  # distance decay: score halves roughly every this many minutes
    price_target: int
    min_group: int
    weights: dict[str, float] = field(default_factory=dict)


PROFILES: dict[str, Profile] = {
    "lunch": Profile("lunch", "Quick team lunch", {"restaurant": 1, "fast_food": 0.8, "food_court": 0.9, "cafe": 0.6, "pub": 0.6},
                     walk_scale_min=8, price_target=1, min_group=6,
                     weights={"distance": 35, "kind": 15, "price": 15, "group": 15, "open": 10, "quality": 10}),
    "dinner": Profile("dinner", "Client dinner", {"restaurant": 1, "pub": 0.4, "cafe": 0.1, "fast_food": 0.05, "food_court": 0.05},
                      walk_scale_min=15, price_target=3, min_group=4,
                      weights={"distance": 15, "kind": 25, "price": 25, "group": 10, "open": 10, "quality": 15}),
    "catering": Profile("catering", "Office catering", {"restaurant": 1, "fast_food": 0.8, "cafe": 0.6, "food_court": 0.5, "pub": 0.3},
                        walk_scale_min=25, price_target=2, min_group=0,
                        weights={"distance": 10, "kind": 10, "price": 10, "group": 0, "open": 10, "quality": 15, "catering": 45}),
    "coffee": Profile("coffee", "Coffee meeting", {"cafe": 1, "restaurant": 0.3, "fast_food": 0.3, "food_court": 0.2, "pub": 0.1},
                      walk_scale_min=6, price_target=1, min_group=2,
                      weights={"distance": 35, "kind": 35, "price": 5, "group": 5, "open": 10, "quality": 10}),
}


@dataclass
class Scored:
    venue: Venue
    score: float
    reasons: list[str]
    blurb: str = ""

    def to_dict(self) -> dict:
        return {"score": round(self.score, 1), "reasons": self.reasons, "blurb": self.blurb, **self.venue.to_dict()}


def _catering_fit(v: Venue) -> float:
    t = v.tags
    if t.get("catering") == "yes" or "catering" in (t.get("description") or "").lower():
        return 1.0
    if t.get("delivery") == "yes":
        return 0.8
    if t.get("takeaway") in ("yes", "only"):
        return 0.6
    return 0.2 if t.get("takeaway") != "no" else 0.0


def score(v: Venue, p: Profile, party: int = 0) -> Scored:
    w = p.weights
    party = party or p.min_group
    parts: dict[str, float] = {
        "distance": math.exp(-v.walk_min / p.walk_scale_min),
        "kind": p.kinds.get(v.kind, 0.3),
        "price": 1 - abs((v.price_level or 2) - p.price_target) / 3,
        "group": min(1.0, v.group_size / party) if party else 1.0,
        "open": {True: 1.0, None: 0.5, False: 0.0}[v.open_now],
        "quality": (bool(v.opening_hours) + bool(v.website) + bool(v.cuisine) + (v.rating or 3.5) / 5) / 4,
        "catering": _catering_fit(v),
    }
    total = sum(w.get(k, 0) * val for k, val in parts.items()) / sum(w.values()) * 100

    reasons = [f"{v.walk_min:.0f} min walk"]
    if v.cuisine:
        reasons.append(", ".join(v.cuisine[:2]))
    if v.diets:
        reasons.append("/".join(sorted(v.diets)))
    if v.open_now is True:
        reasons.append("open at requested time")
    elif v.open_now is False:
        reasons.append("closed at requested time")
    if p.name == "catering" and parts["catering"] >= 0.6:
        reasons.append("catering/delivery/takeaway")
    if party and v.group_size >= party:
        reasons.append(f"fits ~{v.group_size}")
    return Scored(v, total, reasons)


def rank(venues: list[Venue], use_case: str, *, diets: set[str] = frozenset(), party: int = 0,
         open_only: bool = False, max_walk: float | None = None, limit: int = 10) -> list[Scored]:
    p = PROFILES[use_case]
    pool = [v for v in venues
            if set(diets) <= v.diets
            and not (open_only and v.open_now is False)
            and (max_walk is None or v.walk_min <= max_walk)]
    return sorted((score(v, p, party) for v in pool), key=lambda s: (-s.score, s.venue.distance_m))[:limit]

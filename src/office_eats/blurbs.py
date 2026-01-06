"""'Why go here' blurbs: Claude when available, deterministic template otherwise."""
from __future__ import annotations

from .scoring import PROFILES, Scored

PRICE_WORD = {1: "Budget-friendly", 2: "Mid-priced", 3: "Upscale", 4: "Splurge-worthy"}


def deterministic_blurb(s: Scored, use_case: str) -> str:
    v = s.venue
    kind = {"fast_food": "counter-service spot", "cafe": "café", "food_court": "food hall", "pub": "pub"}.get(v.kind, "restaurant")
    cuisine = v.cuisine[0].replace("_", " ") if v.cuisine else ""
    head = f"{PRICE_WORD.get(v.price_level or 2, 'Mid-priced')} {cuisine} {kind}".replace("  ", " ")
    bits = [f"{head}, {v.walk_min:.0f} min on foot"]
    if v.open_now is True:
        bits.append("open when you need it")
    if v.diets:
        bits.append(f"{'/'.join(sorted(v.diets))} options")
    if use_case == "catering" and v.tags.get("catering") == "yes":
        bits.append("does catering")
    elif use_case == "catering" and v.tags.get("delivery") == "yes":
        bits.append("delivers")
    elif use_case in ("lunch", "dinner") and v.group_size >= PROFILES[use_case].min_group:
        bits.append(f"can likely seat ~{v.group_size}")
    return "; ".join(bits) + "."


def apply_deterministic(items: list[Scored], use_case: str) -> str:
    for s in items:
        s.blurb = deterministic_blurb(s, use_case)
    return "deterministic"

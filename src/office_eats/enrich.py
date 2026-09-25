"""Derive cuisine, dietary options, distance and open-now from raw provider data."""
from __future__ import annotations

from datetime import datetime, timedelta

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


def open_for(text: str | None, when: datetime, stay_min: int = 0) -> bool | None:
    """Open for the whole visit: at arrival and still open just before leaving."""
    start = hours.is_open(text, when)
    if not start or stay_min <= 0:
        return start
    return hours.is_open(text, when + timedelta(minutes=stay_min - 1))


def enrich(venues: list[Venue], origin: Place, when: datetime | None = None, stay_min: int = 0) -> list[Venue]:
    for v in venues:
        if not v.cuisine:
            v.cuisine = cuisines(v.tags)
        v.diets |= diets(v.tags, v.cuisine)
        v.menu_url = v.menu_url or v.tags.get("website:menu")
        if v.price_level is None:
            v.price_level, v.price_source = price_hint(v)
        elif v.price_source is None:
            v.price_source = "provider"
        v.group_size = v.group_size or group_size(v)
        v.distance_m = haversine_m(origin.lat, origin.lon, v.lat, v.lon)
        v.walk_min = walk_minutes(v.distance_m)
        if when is not None:
            v.open_now = open_for(v.opening_hours, when, stay_min)
    return venues


# ponytail: OSM has no price data, so these are coarse cuisine/kind heuristics.
# Official providers (Google/Yelp/Foursquare) fill price_level directly and win.
PRICEY = {"steak_house", "steak", "seafood", "sushi", "french", "fine_dining", "wine_bar", "tapas", "omakase"}
CHEAP = {"sandwich", "pizza", "burger", "coffee_shop", "donut", "bubble_tea", "ice_cream", "taco", "tacos",
         "chicken", "hot_dog", "bagel", "juice", "smoothie", "noodle", "dumpling", "kebab", "falafel"}
SNACK_KINDS = {"fast_food", "cafe"}
SNACK_CUISINES = {"coffee_shop", "bubble_tea", "ice_cream", "donut", "juice", "smoothie", "dessert"}


def price_hint(v: Venue) -> tuple[int, str]:
    """(level 1-4, source). Source 'guess' means cuisine/kind heuristics only: low confidence."""
    if v.tags.get("price_range", "").count("$"):  # rare but explicit, e.g. "$$$"
        return max(1, min(4, v.tags["price_range"].count("$"))), "tag"
    if v.kind in SNACK_KINDS or set(v.cuisine) & CHEAP:
        return 1, "guess"
    if set(v.cuisine) & PRICEY or v.tags.get("reservation") in ("yes", "required", "recommended"):
        return 3, "guess"
    return 2, "guess"


def group_size(v: Venue) -> int:
    """Rough max party size the place can seat without drama."""
    try:
        return int(v.tags["capacity"]) // 3  # a third of the room is a big ask already
    except (KeyError, ValueError):
        pass
    if v.kind == "food_court":
        return 20
    if v.cuisine and set(v.cuisine) <= SNACK_CUISINES:
        return 4
    size = {"restaurant": 8, "pub": 12, "cafe": 4, "fast_food": 6}.get(v.kind, 6)
    if v.tags.get("reservation") in ("yes", "recommended", "required"):
        size += 4
    if v.id.startswith(("way/", "relation/")):  # mapped as a whole building footprint
        size += 4
    if v.tags.get("outdoor_seating") not in (None, "no"):
        size += 2
    return size

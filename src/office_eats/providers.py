"""Venue providers. OSM (Overpass) is the default and needs no key; official APIs are opt-in."""
from __future__ import annotations

import os
import urllib.parse
from typing import Protocol

from . import overpass
from .http import Http
from .models import Venue


class ProviderError(RuntimeError):
    pass


class Provider(Protocol):
    name: str

    def nearby(self, lat: float, lon: float, radius_m: int) -> list[Venue]: ...


class OSMProvider:
    name = "osm"

    def __init__(self, http: Http):
        self.http = http

    def nearby(self, lat: float, lon: float, radius_m: int) -> list[Venue]:
        return overpass.fetch_venues(lat, lon, radius_m, self.http)


def _key(env: str) -> str:
    key = os.environ.get(env, "").strip()
    if not key:
        raise ProviderError(f"{env} is not set")
    return key


GOOGLE_PRICE = {"PRICE_LEVEL_INEXPENSIVE": 1, "PRICE_LEVEL_MODERATE": 2,
                "PRICE_LEVEL_EXPENSIVE": 3, "PRICE_LEVEL_VERY_EXPENSIVE": 4}
GOOGLE_KIND = {"cafe": "cafe", "coffee_shop": "cafe", "fast_food_restaurant": "fast_food", "food_court": "food_court",
               "bar": "pub", "pub": "pub"}


class GooglePlacesProvider:
    """Google Places API (New) Nearby Search. Requires GOOGLE_PLACES_API_KEY."""

    name = "google"
    URL = "https://places.googleapis.com/v1/places:searchNearby"
    FIELDS = ("places.id,places.displayName,places.location,places.types,places.primaryType,places.priceLevel,"
              "places.rating,places.websiteUri,places.formattedAddress,places.servesVegetarianFood,"
              "places.takeout,places.delivery,places.reservable,places.nationalPhoneNumber")

    def __init__(self, http: Http):
        self.http, self.key = http, _key("GOOGLE_PLACES_API_KEY")

    def nearby(self, lat: float, lon: float, radius_m: int) -> list[Venue]:
        body = {"includedTypes": ["restaurant", "cafe"], "maxResultCount": 20,
                "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon},
                                                   "radius": float(min(radius_m, 50000))}}}
        data = self.http.fetch(self.URL, json_body=body, ttl=86400,
                               headers={"X-Goog-Api-Key": self.key, "X-Goog-FieldMask": self.FIELDS})
        return [self._venue(p) for p in data.get("places", [])]

    @staticmethod
    def _venue(p: dict) -> Venue:
        types = p.get("types", [])
        tags = {"takeaway": "yes" if p.get("takeout") else "", "delivery": "yes" if p.get("delivery") else "",
                "reservation": "yes" if p.get("reservable") else ""}
        return Venue(
            id=f"google:{p['id']}", name=p.get("displayName", {}).get("text", "?"),
            lat=p["location"]["latitude"], lon=p["location"]["longitude"],
            kind=GOOGLE_KIND.get(p.get("primaryType", ""), "restaurant"),
            cuisine=[t.removesuffix("_restaurant") for t in types if t.endswith("_restaurant") and t != "fast_food_restaurant"],
            diets={"vegetarian"} if p.get("servesVegetarianFood") else set(),
            website=p.get("websiteUri"), address=p.get("formattedAddress"), phone=p.get("nationalPhoneNumber"),
            price_level=GOOGLE_PRICE.get(p.get("priceLevel", "")), rating=p.get("rating"),
            tags={k: v for k, v in tags.items() if v}, source="google",
        )


YELP_KIND = {"cafes": "cafe", "coffee": "cafe", "hotdogs": "fast_food", "foodcourt": "food_court", "pubs": "pub"}
YELP_DIET = {"vegan": "vegan", "vegetarian": "vegetarian", "halal": "halal", "kosher": "kosher", "gluten_free": "gluten_free"}


class YelpProvider:
    """Yelp Fusion business search (official API, not scraping). Requires YELP_API_KEY."""

    name = "yelp"
    URL = "https://api.yelp.com/v3/businesses/search"

    def __init__(self, http: Http):
        self.http, self.key = http, _key("YELP_API_KEY")

    def nearby(self, lat: float, lon: float, radius_m: int) -> list[Venue]:
        params = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "radius": min(radius_m, 40000),
                                         "categories": "restaurants,cafes", "limit": 50, "sort_by": "best_match"})
        data = self.http.fetch(f"{self.URL}?{params}", headers={"Authorization": f"Bearer {self.key}"}, ttl=86400)
        return [self._venue(b) for b in data.get("businesses", [])]

    @staticmethod
    def _venue(b: dict) -> Venue:
        cats = [c["alias"] for c in b.get("categories", [])]
        tx = set(b.get("transactions", []))
        tags = {"takeaway": "yes"} if "pickup" in tx else {}
        if "delivery" in tx:
            tags["delivery"] = "yes"
        if "catering" in cats:
            tags["catering"] = "yes"
        return Venue(
            id=f"yelp:{b['id']}", name=b["name"],
            lat=b["coordinates"]["latitude"], lon=b["coordinates"]["longitude"],
            kind=next((YELP_KIND[c] for c in cats if c in YELP_KIND), "restaurant"),
            cuisine=[c for c in cats if c not in YELP_KIND and c not in YELP_DIET and c != "catering"],
            diets={YELP_DIET[c] for c in cats if c in YELP_DIET},
            address=", ".join(b.get("location", {}).get("display_address", [])) or None,
            phone=b.get("display_phone") or None,
            price_level=len(b["price"]) if b.get("price") else None, rating=b.get("rating"),
            tags=tags, source="yelp",
        )


class FoursquareProvider:
    """Foursquare Places API search. Requires FOURSQUARE_API_KEY (service key)."""

    name = "foursquare"
    URL = "https://places-api.foursquare.com/places/search"
    VERSION = "2025-06-17"

    def __init__(self, http: Http):
        self.http, self.key = http, _key("FOURSQUARE_API_KEY")

    def nearby(self, lat: float, lon: float, radius_m: int) -> list[Venue]:
        params = urllib.parse.urlencode({"ll": f"{lat},{lon}", "radius": min(radius_m, 100000),
                                         "query": "restaurant", "limit": 50})
        data = self.http.fetch(f"{self.URL}?{params}", ttl=86400, headers={
            "Authorization": f"Bearer {self.key}", "X-Places-Api-Version": self.VERSION, "Accept": "application/json"})
        return [self._venue(r) for r in data.get("results", [])]

    @staticmethod
    def _venue(r: dict) -> Venue:
        cats = [c.get("name", "").lower() for c in r.get("categories", [])]
        kind = "cafe" if any("caf" in c or "coffee" in c for c in cats) else \
            "fast_food" if any("fast food" in c for c in cats) else "restaurant"
        return Venue(
            id=f"foursquare:{r['fsq_place_id']}", name=r["name"], lat=r["latitude"], lon=r["longitude"], kind=kind,
            cuisine=[c.removesuffix(" restaurant") for c in cats if c.endswith("restaurant")],
            diets={d for d in ("vegan", "vegetarian", "halal", "kosher") if any(d in c for c in cats)},
            website=r.get("website"), phone=r.get("tel"),
            address=r.get("location", {}).get("formatted_address"), source="foursquare",
        )


REGISTRY: dict[str, type] = {"osm": OSMProvider, "google": GooglePlacesProvider, "yelp": YelpProvider,
                             "foursquare": FoursquareProvider}


def get_provider(name: str, http: Http) -> Provider:
    try:
        return REGISTRY[name](http)
    except KeyError:
        raise ProviderError(f"unknown provider {name!r}; choose from {sorted(REGISTRY)}") from None

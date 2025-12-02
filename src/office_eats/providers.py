"""Venue providers. OSM (Overpass) is the default and needs no key; official APIs are opt-in."""
from __future__ import annotations

import os
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


REGISTRY: dict[str, type] = {"osm": OSMProvider, "google": GooglePlacesProvider}


def get_provider(name: str, http: Http) -> Provider:
    try:
        return REGISTRY[name](http)
    except KeyError:
        raise ProviderError(f"unknown provider {name!r}; choose from {sorted(REGISTRY)}") from None

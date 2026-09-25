"""Nearby food venues from the OpenStreetMap Overpass API."""
from __future__ import annotations

from .http import Http
from .models import Venue

OVERPASS = "https://overpass-api.de/api/interpreter"
AMENITIES = ("restaurant", "cafe", "fast_food", "food_court", "pub")


def build_query(lat: float, lon: float, radius_m: int) -> str:
    amen = "|".join(AMENITIES)
    return (
        f"[out:json][timeout:25];"
        f'nwr["amenity"~"^({amen})$"]["name"](around:{int(radius_m)},{lat:.6f},{lon:.6f});'
        f"out center tags;"
    )


def parse_elements(data: dict) -> list[Venue]:
    venues = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        lat = el.get("lat", el.get("center", {}).get("lat"))
        lon = el.get("lon", el.get("center", {}).get("lon"))
        if lat is None or lon is None or not tags.get("name"):
            continue
        addr = " ".join(filter(None, [tags.get("addr:housenumber"), tags.get("addr:street")])) or None
        venues.append(Venue(
            id=f"{el['type']}/{el['id']}",
            name=tags["name"],
            lat=float(lat),
            lon=float(lon),
            kind=tags.get("amenity", "restaurant"),
            opening_hours=tags.get("opening_hours"),
            website=tags.get("website") or tags.get("contact:website"),
            phone=tags.get("phone") or tags.get("contact:phone"),
            address=addr,
            tags=tags,
        ))
    return venues


def fetch_venues(lat: float, lon: float, radius_m: int, http: Http) -> list[Venue]:
    data = http.fetch(OVERPASS, data={"data": build_query(lat, lon, radius_m)}, ttl=7 * 86400)
    return parse_elements(data)

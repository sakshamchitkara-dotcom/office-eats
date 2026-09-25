"""Geocoding via OpenStreetMap Nominatim (usage policy: <=1 req/s, identifying UA, cache results)."""
from __future__ import annotations

import re
import urllib.parse

from .http import Http
from .models import Place

NOMINATIM = "https://nominatim.openstreetmap.org/search"
_LATLON = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


class GeocodeError(ValueError):
    pass


def parse_latlon(text: str) -> tuple[float, float] | None:
    m = _LATLON.match(text)
    if not m:
        return None
    lat, lon = float(m[1]), float(m[2])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise GeocodeError(f"coordinates out of range: {text}")
    return lat, lon


def geocode(query: str, http: Http, name: str | None = None) -> Place:
    """Accepts 'lat,lon' or a free-form address/company name."""
    if coords := parse_latlon(query):
        return Place(name or query, *coords)
    params = urllib.parse.urlencode({"q": query, "format": "jsonv2", "limit": 1})
    results = http.fetch(f"{NOMINATIM}?{params}", ttl=30 * 86400)  # addresses rarely move
    if not results:
        raise GeocodeError(f"no geocoding result for {query!r}")
    r = results[0]
    return Place(name or r.get("name") or query, float(r["lat"]), float(r["lon"]), r.get("display_name", ""))

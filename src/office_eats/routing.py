"""Routed walking times: OSRM (FOSSGIS foot server, no key) or OpenRouteService (ORS_API_KEY).

One matrix request per chunk of venues (office -> every venue), cached for 30 days by the Http layer.
Any failure leaves the straight-line x1.3 estimate in place, so routing can only make things better.
"""
from __future__ import annotations

import os
import sys

from .http import Http, HttpError
from .models import Place, Venue

OSRM_FOOT = "https://routing.openstreetmap.de/routed-foot/table/v1/foot"
ORS_MATRIX = "https://api.openrouteservice.org/v2/matrix/foot-walking"
CHUNK = 50  # destinations per request; both public servers cap matrix size
TTL = 30 * 86400
ENGINES = ("none", "osrm", "ors")


class RoutingError(RuntimeError):
    pass


def _osrm(origin: Place, venues: list[Venue], http: Http) -> list[tuple[float | None, float | None]]:
    coords = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in [(origin.lat, origin.lon)] + [(v.lat, v.lon) for v in venues])
    data = http.fetch(f"{OSRM_FOOT}/{coords}?sources=0&annotations=duration,distance", ttl=TTL)
    if data.get("code") != "Ok":
        raise RoutingError(f"OSRM: {data.get('code')} {data.get('message', '')}".strip())
    # Destinations are every coordinate, so index 0 is the office itself.
    return list(zip(data["durations"][0][1:], data["distances"][0][1:], strict=True))


def _ors(origin: Place, venues: list[Venue], http: Http) -> list[tuple[float | None, float | None]]:
    key = os.environ.get("ORS_API_KEY", "").strip()
    if not key:
        raise RoutingError("ORS_API_KEY is not set")
    body = {"locations": [[origin.lon, origin.lat]] + [[v.lon, v.lat] for v in venues],
            "sources": [0], "destinations": list(range(1, len(venues) + 1)), "metrics": ["duration", "distance"]}
    data = http.fetch(ORS_MATRIX, json_body=body, headers={"Authorization": key}, ttl=TTL)
    return list(zip(data["durations"][0], data["distances"][0], strict=True))


def apply_routing(venues: list[Venue], origin: Place, http: Http, engine: str = "osrm") -> str:
    """Overwrite walk_min/distance_m with routed values where the engine found a route.

    Returns a label for reports: the engine name, or the fallback description when nothing was routed.
    """
    fallback = "straight-line x1.3"
    if engine == "none" or not venues:
        return fallback
    fetch = {"osrm": _osrm, "ors": _ors}[engine]
    routed = 0
    try:
        for i in range(0, len(venues), CHUNK):
            chunk = venues[i:i + CHUNK]
            for v, (secs, metres) in zip(chunk, fetch(origin, chunk, http), strict=True):
                if secs is None:  # unroutable (e.g. snapped to a different island): keep the estimate
                    continue
                v.walk_min, v.walk_routed = secs / 60, True
                if metres is not None:
                    v.distance_m = metres
                routed += 1
    except (HttpError, RoutingError, KeyError, ValueError, TypeError) as e:
        print(f"office-eats: routing via {engine} failed, using straight-line estimates ({e})", file=sys.stderr)
    return f"{engine} walking routes" if routed else fallback

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


REGISTRY: dict[str, type] = {"osm": OSMProvider}


def get_provider(name: str, http: Http) -> Provider:
    try:
        return REGISTRY[name](http)
    except KeyError:
        raise ProviderError(f"unknown provider {name!r}; choose from {sorted(REGISTRY)}") from None

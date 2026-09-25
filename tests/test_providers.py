import pytest

from conftest import load
from office_eats.providers import ProviderError, get_provider


def test_osm_provider(fake_http):
    p = get_provider("osm", fake_http({"overpass": load("overpass_adobe_800m.json")}))
    assert len(p.nearby(37.33, -121.89, 800)) >= 90


def test_unknown_provider(fake_http):
    with pytest.raises(ProviderError):
        get_provider("nope", fake_http({}))


def test_google_requires_key(fake_http, monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="GOOGLE_PLACES_API_KEY"):
        get_provider("google", fake_http({}))


def test_google_mapping(fake_http, monkeypatch):
    # Fixture is hand-written from the documented Places API (New) response shape, not recorded.
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "k")
    http = fake_http({"places.googleapis.com": load("google_nearby.json")})
    a, b = get_provider("google", http).nearby(37.33, -121.89, 800)
    assert (a.name, a.kind, a.cuisine, a.price_level, a.rating) == ("Example Trattoria", "restaurant", ["italian"], 3, 4.6)
    assert a.diets == {"vegetarian"} and a.tags == {"takeaway": "yes", "reservation": "yes"}
    assert (b.kind, b.price_level) == ("cafe", 1)

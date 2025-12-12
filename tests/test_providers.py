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


def test_yelp_mapping(fake_http, monkeypatch):
    # Hand-written from the documented Yelp Fusion response shape, not recorded.
    monkeypatch.setenv("YELP_API_KEY", "k")
    http = fake_http({"api.yelp.com": load("yelp_search.json")})
    a, b = get_provider("yelp", http).nearby(37.33, -121.89, 800)
    assert (a.cuisine, a.diets, a.price_level, a.rating) == (["mexican"], {"vegan"}, 1, 4.5)
    assert a.tags == {"takeaway": "yes", "delivery": "yes", "catering": "yes"}
    assert "San Jose" in a.address and b.kind == "cafe" and b.price_level is None
    assert "radius=800" in http.calls[0][0]


def test_foursquare_mapping(fake_http, monkeypatch):
    # Hand-written from the documented Foursquare Places response shape, not recorded.
    monkeypatch.setenv("FOURSQUARE_API_KEY", "k")
    http = fake_http({"places-api.foursquare.com": load("foursquare_search.json")})
    a, b = get_provider("foursquare", http).nearby(37.33, -121.89, 800)
    assert a.diets == {"halal"} and a.cuisine == ["halal", "middle eastern"] and a.website
    assert b.kind == "cafe"

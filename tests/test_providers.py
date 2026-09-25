import pytest

from conftest import load
from office_eats.providers import ProviderError, get_provider


def test_osm_provider(fake_http):
    p = get_provider("osm", fake_http({"overpass": load("overpass_adobe_800m.json")}))
    assert len(p.nearby(37.33, -121.89, 800)) >= 90


def test_unknown_provider(fake_http):
    with pytest.raises(ProviderError):
        get_provider("nope", fake_http({}))

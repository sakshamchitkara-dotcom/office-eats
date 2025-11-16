import pytest

from conftest import load
from office_eats.geocode import GeocodeError, geocode, parse_latlon


def test_latlon_short_circuits(fake_http):
    http = fake_http({})
    p = geocode("37.33, -121.89", http, name="HQ")
    assert (p.name, p.lat, p.lon) == ("HQ", 37.33, -121.89) and http.calls == []


def test_out_of_range():
    with pytest.raises(GeocodeError):
        parse_latlon("123,0")


def test_nominatim_fixture(fake_http):
    http = fake_http({"nominatim": load("nominatim_adobe.json")})
    p = geocode("345 Park Ave, San Jose, CA 95110", http, name="Adobe HQ")
    assert round(p.lat, 3) == 37.329 and round(p.lon, 3) == -121.895
    assert "San Jose" in p.address


def test_no_result(fake_http):
    with pytest.raises(GeocodeError):
        geocode("nowhere at all", fake_http({"nominatim": []}))

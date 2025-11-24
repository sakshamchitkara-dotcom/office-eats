from conftest import load
from office_eats.overpass import build_query, fetch_venues, parse_elements


def test_query_shape():
    q = build_query(37.33, -121.89, 800)
    assert "around:800,37.330000,-121.890000" in q and "restaurant|cafe" in q and "out center" in q


def test_parse_real_fixture():
    venues = parse_elements(load("overpass_adobe_800m.json"))
    assert len(venues) >= 90
    assert all(v.name and v.lat and v.lon for v in venues)
    ways = [v for v in venues if v.id.startswith("way/")]
    assert ways, "ways must use their center coordinates"
    assert {v.kind for v in venues} <= {"restaurant", "cafe", "fast_food", "food_court", "pub"}


def test_skips_unnamed_and_centerless():
    data = {"elements": [
        {"type": "node", "id": 1, "lat": 1, "lon": 2, "tags": {"amenity": "cafe"}},
        {"type": "way", "id": 2, "tags": {"amenity": "cafe", "name": "No center"}},
    ]}
    assert parse_elements(data) == []


def test_fetch_posts_query(fake_http):
    http = fake_http({"overpass": load("overpass_adobe_800m.json")})
    fetch_venues(37.33, -121.89, 800, http)
    url, data = http.calls[0]
    assert "around:800" in data["data"]

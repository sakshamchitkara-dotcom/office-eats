from office_eats.models import Venue, haversine_m, osm_link, walk_minutes


def test_haversine_known_distance():
    # SF Ferry Building -> Salesforce Tower is ~0.7 km
    d = haversine_m(37.7955, -122.3937, 37.7897, -122.3972)
    assert 650 < d < 750


def test_walk_minutes_uses_detour():
    assert round(walk_minutes(800), 1) == 13.0


def test_osm_link_for_node_and_foreign():
    assert osm_link(Venue("node/42", "x", 1, 2)) == "https://www.openstreetmap.org/node/42"
    v = Venue("yelp:abc", "x", 37.1, -122.2, source="yelp")
    assert "mlat=37.100000" in osm_link(v)

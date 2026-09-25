from datetime import datetime

from conftest import load
from office_eats.enrich import cuisines, diets, enrich
from office_eats.models import Place, Venue
from office_eats.overpass import parse_elements


def test_cuisine_split():
    assert cuisines({"cuisine": "Mexican;tacos, burrito"}) == ["mexican", "tacos", "burrito"]


def test_diets_from_tags_and_cuisine():
    assert diets({"diet:vegan": "yes", "diet:halal": "no"}, []) == {"vegan", "vegetarian"}
    assert diets({"diet:gluten_free": "only"}, []) == {"gluten_free"}
    assert diets({}, ["falafel"]) == {"vegetarian"}


def test_enrich_distance_and_open_now():
    origin = Place("HQ", 37.3294709, -121.8947723)
    v = Venue("node/1", "Cafe", 37.3304, -121.8947, opening_hours="Mo-Fr 07:00-15:00")
    enrich([v], origin, datetime(2026, 9, 21, 12, 0))
    assert 90 < v.distance_m < 120 and v.walk_min > 1 and v.open_now is True


def test_enrich_real_fixture_has_diet_signal():
    origin = Place("HQ", 37.3294709, -121.8947723)
    vs = enrich(parse_elements(load("overpass_adobe_800m.json")), origin)
    assert any(v.diets for v in vs)
    assert all(v.distance_m < 1000 for v in vs)  # around:800 plus way-center slack


def test_price_hint():
    from office_eats.enrich import price_hint
    assert price_hint(Venue("n/1", "a", 0, 0, kind="fast_food")) == 1
    assert price_hint(Venue("n/1", "a", 0, 0, cuisine=["steak_house"])) == 3
    assert price_hint(Venue("n/1", "a", 0, 0, tags={"price_range": "$$$$"})) == 4
    assert price_hint(Venue("n/1", "a", 0, 0, cuisine=["italian"])) == 2


def test_provider_price_wins():
    v = Venue("n/1", "a", 0, 0, kind="fast_food", price_level=3)
    enrich([v], Place("o", 0, 0))
    assert v.price_level == 3


def test_group_size():
    from office_eats.enrich import group_size
    assert group_size(Venue("n/1", "a", 0, 0, tags={"capacity": "48"})) == 16
    assert group_size(Venue("n/1", "a", 0, 0, kind="cafe", cuisine=["bubble_tea"])) == 4
    big = Venue("way/1", "a", 0, 0, tags={"reservation": "yes", "outdoor_seating": "yes"})
    assert group_size(big) == 8 + 4 + 4 + 2

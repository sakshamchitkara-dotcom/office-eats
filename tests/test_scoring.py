from conftest import load
from office_eats.enrich import enrich
from office_eats.models import Place, Venue
from office_eats.overpass import parse_elements
from office_eats.scoring import PROFILES, rank, score

ORIGIN = Place("Adobe HQ", 37.3294709, -121.8947723)


def mk(**kw):
    v = Venue(kw.pop("id", "node/1"), kw.pop("name", "x"), ORIGIN.lat, ORIGIN.lon, **kw)
    return enrich([v], ORIGIN)[0]


def test_closer_scores_higher():
    near, far = mk(), mk()
    far.walk_min = 20
    p = PROFILES["lunch"]
    assert score(near, p).score > score(far, p).score


def test_coffee_prefers_cafe_dinner_prefers_restaurant():
    cafe = mk(kind="cafe", cuisine=["coffee_shop"])
    rest = mk(kind="restaurant", cuisine=["steak_house"])
    assert score(cafe, PROFILES["coffee"]).score > score(rest, PROFILES["coffee"]).score
    assert score(rest, PROFILES["dinner"]).score > score(cafe, PROFILES["dinner"]).score


def test_catering_rewards_catering_tag():
    a = mk(tags={"catering": "yes"})
    b = mk(tags={"takeaway": "no"})
    assert score(a, PROFILES["catering"]).score > score(b, PROFILES["catering"]).score + 30


def test_diet_filter_is_hard():
    vs = [mk(id="node/1", diets={"vegan", "vegetarian"}), mk(id="node/2")]
    assert [s.venue.id for s in rank(vs, "lunch", diets={"vegan"})] == ["node/1"]


def test_open_only_drops_closed_but_keeps_unknown():
    a, b, c = mk(id="node/a"), mk(id="node/b"), mk(id="node/c")
    a.open_now, b.open_now, c.open_now = True, False, None
    assert {s.venue.id for s in rank([a, b, c], "lunch", open_only=True)} == {"node/a", "node/c"}


def test_rank_real_fixture_every_use_case():
    vs = enrich(parse_elements(load("overpass_adobe_800m.json")), ORIGIN)
    for uc in PROFILES:
        top = rank(vs, uc, limit=5)
        assert len(top) == 5
        assert top == sorted(top, key=lambda s: -s.score)
        assert all(0 <= s.score <= 100 for s in top)
    assert all(s.venue.kind == "cafe" for s in rank(vs, "coffee", limit=3))


def test_wheelchair_keeps_only_tagged_accessible_places():
    vs = [mk(id=f"node/{t or 'none'}", tags={"wheelchair": t} if t else {}) for t in ("yes", "designated", "limited", "no", None)]
    assert [s.venue.id for s in rank(vs, "lunch", wheelchair=True)] == ["node/yes", "node/designated"]
    assert len(rank(vs, "lunch")) == 5


def test_wheelchair_flag_on_the_recorded_fixture():
    vs = parse_elements(load("overpass_adobe_800m.json"))
    enrich(vs, ORIGIN)
    picks = rank(vs, "lunch", wheelchair=True, limit=50)
    assert len(picks) == 7 and all(s.venue.tags["wheelchair"] == "yes" for s in picks)

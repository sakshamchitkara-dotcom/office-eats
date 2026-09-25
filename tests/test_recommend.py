from datetime import datetime

import pytest

from conftest import load
from office_eats.recommend import Query, recommend


def routes():
    return {"nominatim": load("nominatim_adobe.json"), "overpass": load("overpass_adobe_800m.json")}


def test_end_to_end_offline(fake_http):
    http = fake_http(routes())
    q = Query("345 Park Ave, San Jose, CA 95110", name="Adobe HQ", when=datetime(2026, 9, 22, 12, 0), limit=5)
    r = recommend(q, http)
    assert r.place.name == "Adobe HQ" and r.candidates >= 90 and len(r.items) == 5
    d = r.to_dict()
    assert d["query"]["when"] == "2026-09-22T12:00:00" and d["recommendations"][0]["score"] > 0
    assert "around:800" in http.calls[1][1]["data"]


def test_max_walk_sets_radius():
    assert Query("x", max_walk=10).radius() == 615
    assert Query("x", use_case="catering").radius() == 3000
    assert Query("x", radius_m=250).radius() == 250


def test_bad_use_case(fake_http):
    with pytest.raises(ValueError):
        recommend(Query("1,1", use_case="brunch"), fake_http({}))

import json
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


def test_llm_off_uses_deterministic_blurbs(fake_http, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    r = recommend(Query("1,1", llm="off", limit=3), fake_http(routes()))
    assert r.blurb_source == "deterministic" and all(s.blurb for s in r.items)


def test_llm_failure_falls_back(fake_http, capsys):
    class Boom:
        @property
        def messages(self):
            raise ConnectionError("offline")
    r = recommend(Query("37.33,-121.89", llm="on", limit=3), fake_http(routes()), llm_client=Boom())
    assert r.blurb_source == "deterministic" and len(r.items) == 3 and all(s.blurb for s in r.items)
    assert "Claude unavailable" in capsys.readouterr().err


def test_llm_success_path(fake_http):
    from test_claude_blurbs import FakeClient
    r0 = recommend(Query("37.33,-121.89", llm="off", limit=3), fake_http(routes()))
    pick = r0.items[2].venue.id
    c = FakeClient([{"id": pick, "blurb": "Chosen by Claude."}])
    r = recommend(Query("37.33,-121.89", llm="on", limit=3), fake_http(routes()), llm_client=c)
    assert r.blurb_source.startswith("claude") and r.items[0].venue.id == pick and r.items[0].blurb == "Chosen by Claude."
    assert len(json.loads(c.kwargs["messages"][0]["content"])["candidates"]) == 6

from office_eats.http import HttpError
from office_eats.models import Place, Venue
from office_eats.routing import CHUNK, apply_routing

HQ = Place("HQ", 37.329471, -121.894772)


def venues(n):
    return [Venue(f"node/{i}", f"v{i}", 37.33 + i * 1e-4, -121.89, walk_min=9.0, distance_m=500.0) for i in range(n)]


def test_osrm_overwrites_walk_and_distance(fake_http):
    vs = venues(2)
    # Real response shape from routing.openstreetmap.de (index 0 is the office itself).
    http = fake_http({"routed-foot": {"code": "Ok", "durations": [[0, 159.3, None]], "distances": [[0, 199.4, None]]}})
    assert apply_routing(vs, HQ, http, "osrm") == "osrm walking routes"
    assert (round(vs[0].walk_min, 2), vs[0].distance_m, vs[0].walk_routed) == (2.66, 199.4, True)
    assert (vs[1].walk_min, vs[1].walk_routed) == (9.0, False)  # unroutable keeps the estimate
    assert "sources=0" in http.calls[0][0] and "-121.894772,37.329471;" in http.calls[0][0]


def test_chunks_large_candidate_sets(fake_http):
    vs = venues(CHUNK + 3)

    def answer(url, data):
        n = url.split("/foot/")[1].split("?")[0].count(";")
        return {"code": "Ok", "durations": [[0] + [60.0] * n], "distances": [[0] + [80.0] * n]}

    http = fake_http({"routed-foot": answer})
    apply_routing(vs, HQ, http, "osrm")
    assert len(http.calls) == 2 and all(v.walk_min == 1.0 for v in vs)


def test_failure_falls_back(fake_http, capsys):
    vs = venues(1)

    def boom(url, data):
        raise HttpError("routing.openstreetmap.de: timed out")

    assert apply_routing(vs, HQ, fake_http({"routed-foot": boom}), "osrm") == "straight-line x1.3"
    assert vs[0].walk_min == 9.0 and "routing via osrm failed" in capsys.readouterr().err


def test_ors_needs_key_and_sends_matrix(fake_http, monkeypatch, capsys):
    monkeypatch.delenv("ORS_API_KEY", raising=False)
    assert apply_routing(venues(1), HQ, fake_http({}), "ors") == "straight-line x1.3"
    assert "ORS_API_KEY" in capsys.readouterr().err
    monkeypatch.setenv("ORS_API_KEY", "k")
    http = fake_http({"openrouteservice": {"durations": [[120.0]], "distances": [[150.0]]}})
    vs = venues(1)
    assert apply_routing(vs, HQ, http, "ors") == "ors walking routes"
    assert http.calls[0][1]["destinations"] == [1] and vs[0].walk_min == 2.0


def test_none_is_a_noop(fake_http):
    assert apply_routing(venues(1), HQ, fake_http({}), "none") == "straight-line x1.3"

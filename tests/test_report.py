import json
from datetime import datetime

import pytest

from conftest import load
from office_eats import report
from office_eats.models import Place, Venue
from office_eats.recommend import Query, Result, recommend
from office_eats.scoring import Scored


@pytest.fixture
def result(fake_http):
    http = fake_http({"nominatim": load("nominatim_adobe.json"), "overpass": load("overpass_adobe_800m.json")})
    return recommend(Query("345 Park Ave, San Jose", name="Adobe HQ", when=datetime(2026, 9, 22, 12), limit=4), http)


def test_table(result):
    out = report.table(result)
    assert out.splitlines()[0] == "Quick team lunch near Adobe HQ"
    assert len(out.splitlines()) == 5 + 4


def test_markdown_has_osm_links(result):
    md = report.markdown(result)
    assert md.count("https://www.openstreetmap.org/") >= 5 and "ODbL" in md


def test_json_roundtrip(result):
    d = json.loads(report.to_json(result))
    assert len(d["recommendations"]) == 4 and d["use_case_label"] == "Quick team lunch"


def test_html_escapes_untrusted_names():
    v = Venue("node/1", "<script>alert(1)</script>", 0, 0, website='https://x.test/"onmouseover=1')
    r = Result(Query("0,0"), Place("HQ", 0, 0), [Scored(v, 50, ["close"])], 1)
    out = report.to_html(r)
    assert "<script>alert" not in out and "&lt;script&gt;" in out and '"onmouseover' not in out


def test_empty_table():
    r = Result(Query("0,0"), Place("HQ", 0, 0), [], 0)
    assert "no matches" in report.table(r)


def test_non_http_links_dropped():
    v = Venue("node/1", "x", 0, 0, website="javascript:alert(1)", menu_url="https://ok.test/menu")
    r = Result(Query("0,0"), Place("HQ", 0, 0), [Scored(v, 50, [])], 1)
    for out in (report.to_html(r), report.markdown(r)):
        assert "javascript:" not in out and "https://ok.test/menu" in out

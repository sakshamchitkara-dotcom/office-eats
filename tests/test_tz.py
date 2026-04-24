from datetime import datetime, timezone

import pytest

from office_eats import tz


@pytest.fixture
def no_finder(monkeypatch):
    monkeypatch.setattr(tz, "_timezonefinder", lambda lat, lon: None)


def test_override_wins_and_is_validated(fake_http):
    assert str(tz.office_tz(0, 0, override="Asia/Kolkata")) == "Asia/Kolkata"
    with pytest.raises(ValueError, match="unknown time zone"):
        tz.office_tz(0, 0, override="Mars/Olympus")


def test_timezonefinder_used_when_installed(monkeypatch, fake_http):
    monkeypatch.setattr(tz, "_timezonefinder", lambda lat, lon: "America/Los_Angeles")
    assert str(tz.office_tz(37.33, -121.89, fake_http({}))) == "America/Los_Angeles"  # no network call


def test_osm_boundary_tag_fallback_prefers_smallest_area(no_finder, fake_http):
    http = fake_http({"overpass": {"elements": [
        {"type": "area", "tags": {"admin_level": "2", "timezone": "America/New_York"}},
        {"type": "area", "tags": {"admin_level": "4", "timezone": "America/Los_Angeles"}},
        {"type": "area", "tags": {"admin_level": "6", "timezone": "not/a_zone"}},
    ]}})
    assert str(tz.office_tz(37.33, -121.89, http)) == "America/Los_Angeles"
    assert "is_in(37.33000,-121.89000)" in http.calls[0][1]["data"]


def test_lookup_failure_returns_none(no_finder, fake_http, capsys):
    from office_eats.http import HttpError

    def busy(url, data):
        raise HttpError("overpass-api.de: HTTP Error 504", 504)

    assert tz.office_tz(1, 1, fake_http({"overpass": busy})) is None
    assert "time zone lookup failed" in capsys.readouterr().err
    assert tz.office_tz(1, 1) is None


def test_to_office_time():
    la = tz.office_tz(0, 0, override="America/Los_Angeles")
    utc_noon = datetime(2026, 9, 25, 19, 0, tzinfo=timezone.utc)
    assert tz.to_office_time(utc_noon, la) == datetime(2026, 9, 25, 12, 0)
    assert tz.to_office_time(datetime(2026, 9, 25, 12, 0), la) == datetime(2026, 9, 25, 12, 0)


def test_at_is_resolved_against_the_office_clock(fake_http, monkeypatch):
    from conftest import load
    from office_eats.recommend import Query, recommend

    http = fake_http({"overpass": load("overpass_adobe_800m.json")})
    q = Query("37.3295,-121.8948", at="2026-09-25T19:00+00:00", tz="America/Los_Angeles", limit=1)
    r = recommend(q, http)
    assert r.query.when == datetime(2026, 9, 25, 12, 0) and r.timezone == "America/Los_Angeles"
    assert r.to_dict()["timezone"] == "America/Los_Angeles"
    now = recommend(Query("37.3295,-121.8948", at="now", tz="Asia/Tokyo", limit=1), http).query.when
    tokyo_now = datetime.now(timezone.utc).astimezone(tz.office_tz(0, 0, override="Asia/Tokyo")).replace(tzinfo=None)
    assert abs((tokyo_now - now).total_seconds()) < 120


def test_no_time_means_no_zone_lookup(fake_http, no_finder):
    from conftest import load
    from office_eats.recommend import Query, recommend

    http = fake_http({"overpass": load("overpass_adobe_800m.json")})
    assert recommend(Query("37.3295,-121.8948", limit=1), http).timezone is None
    assert len(http.calls) == 1  # venues only

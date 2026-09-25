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

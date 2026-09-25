import argparse
from datetime import datetime

import pytest

from conftest import load
from office_eats import cli

MON_NOON = datetime(2026, 9, 21, 12, 0)


def test_parse_when():
    assert cli.parse_when("fri 19:00", MON_NOON) == datetime(2026, 9, 25, 19, 0)
    assert cli.parse_when("mon 11:00", MON_NOON) == datetime(2026, 9, 28, 11, 0)  # already passed today
    assert cli.parse_when("2026-10-01 12:30") == datetime(2026, 10, 1, 12, 30)
    assert cli.parse_when(None) is None


def test_parse_diets():
    assert cli.parse_diets("Vegan, gluten-free") == {"vegan", "gluten_free"}
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_diets("paleo")


@pytest.fixture
def offline(monkeypatch, fake_http):
    http = fake_http({"nominatim": load("nominatim_adobe.json"), "overpass": load("overpass_adobe_800m.json")})
    monkeypatch.setattr(cli, "make_http", lambda a: http)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return http


def test_recommend_table(offline, capsys):
    assert cli.main(["recommend", "345 Park Ave, San Jose", "--name", "Adobe HQ", "-n", "3", "--at", "2026-09-22 12:00"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Quick team lunch near Adobe HQ") and len(out.strip().splitlines()) == 8


def test_recommend_writes_file(offline, tmp_path):
    out = tmp_path / "r.html"
    assert cli.main(["recommend", "37.33,-121.89", "-f", "html", "-o", str(out), "-u", "dinner"]) == 0
    assert out.read_text().startswith("<!doctype html>")


def test_error_exit_code(monkeypatch, fake_http, capsys):
    monkeypatch.setattr(cli, "make_http", lambda a: fake_http({"nominatim": []}))
    assert cli.main(["recommend", "Atlantis"]) == 2
    assert "no geocoding result" in capsys.readouterr().err

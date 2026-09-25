import argparse
from datetime import datetime

import pytest

from conftest import load
from office_eats import cli
from office_eats.tz import parse_when

MON_NOON = datetime(2026, 9, 21, 12, 0)


def test_parse_when():
    assert parse_when("fri 19:00", MON_NOON) == datetime(2026, 9, 25, 19, 0)
    assert parse_when("mon 11:00", MON_NOON) == datetime(2026, 9, 28, 11, 0)  # already passed today
    assert parse_when("2026-10-01 12:30") == datetime(2026, 10, 1, 12, 30)
    assert parse_when(None) is None
    for bad in ("fri 7pm", "fri", "tomorrow", "fri 25:00"):
        with pytest.raises(ValueError, match="can't read time"):
            parse_when(bad, MON_NOON)


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


def test_read_offices(tmp_path):
    p = tmp_path / "o.csv"
    p.write_text("Name,Address,lat,lon,diet\nA,1 Main St,,,vegan\nB,,37.1,-122.2,\n")
    a, b = cli.read_offices(str(p))
    assert (a["location"], a["diet"], b["location"]) == ("1 Main St", "vegan", "37.1,-122.2")
    p.write_text("name,address\nC,\n")
    with pytest.raises(ValueError, match=":2"):
        cli.read_offices(str(p))


def test_batch_writes_one_file_per_office(offline, tmp_path):
    csv = tmp_path / "o.csv"
    csv.write_text("name,lat,lon,use_case,diet\nAdobe HQ,37.3294,-121.8947,dinner,\nSecond Office!,37.33,-121.89,,vegan\n")
    assert cli.main(["batch", str(csv), "--out-dir", str(tmp_path / "out"), "-f", "md"]) == 0
    files = sorted(f.name for f in (tmp_path / "out").iterdir())
    assert files == ["adobe-hq.md", "second-office.md"]
    assert (tmp_path / "out" / "adobe-hq.md").read_text().startswith("# Client dinner near Adobe HQ")
    assert "Dietary filter: vegan" in (tmp_path / "out" / "second-office.md").read_text()


def test_batch_bad_row_does_not_stop_the_rest(offline, tmp_path, capsys):
    csv = tmp_path / "o.csv"
    csv.write_text("name,lat,lon,diet,party\nBad Diet,37.33,-121.89,paleo,\nBad Party,37.33,-121.89,,six\nGood,37.33,-121.89,,4\n")
    assert cli.main(["batch", str(csv), "--out-dir", str(tmp_path / "out")]) == 1
    assert [f.name for f in (tmp_path / "out").iterdir()] == ["good.txt"]
    err = capsys.readouterr().err
    assert "Bad Diet: unknown diet" in err and "Bad Party: invalid literal" in err


def test_poll_invite_prints_signed_links(monkeypatch, capsys):
    from office_eats.store import Store
    store = Store(":memory:")
    monkeypatch.setattr(cli, "make_store", lambda: store)
    pid = store.create_poll("t", [{"id": "a", "name": "A", "url": "u", "walk_min": 1, "blurb": ""}] * 2)
    assert cli.main(["poll", "invite", pid, "ana", "bo b", "--base-url", "https://eats.example/"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == f"ana\thttps://eats.example/poll/{pid}?voter=ana&t={store.invite_token(pid, 'ana')}"
    assert lines[1].startswith(f"bo b\thttps://eats.example/poll/{pid}?voter=bo+b&t=")

import pytest

from office_eats import cli
from office_eats.store import Store, StoreError


@pytest.fixture
def store(monkeypatch):
    s = Store(":memory:")
    monkeypatch.setattr(cli, "make_store", lambda: s)
    return s


def test_team_profile_create_update_show(store, capsys):
    assert cli.main(["team", "set", "Platform", "--office", "345 Park Ave, San Jose", "--office-name", "Adobe HQ",
                     "--diet", "vegetarian,gluten-free", "--party", "7"]) == 0
    assert cli.main(["team", "set", "Platform", "--party", "9"]) == 0  # partial update keeps the rest
    t = store.team("Platform")
    assert (t["location"], t["diets"], t["party"], t["tz"]) == ("345 Park Ave, San Jose", ["gluten_free", "vegetarian"], 9, None)
    assert cli.main(["team", "set", "Platform", "--diet", ""]) == 0
    assert store.team("Platform")["diets"] == []
    capsys.readouterr()
    assert cli.main(["team", "list"]) == 0
    assert capsys.readouterr().out.startswith("Platform: Adobe HQ (345 Park Ave, San Jose) · diet: any · party: 9")


def test_team_errors(store, capsys):
    assert cli.main(["team", "set", "New"]) == 2
    assert "needs an office location" in capsys.readouterr().err
    assert cli.main(["team", "set", "New", "--office", "1,1", "--diet", "paleo"]) == 2
    with pytest.raises(StoreError, match="no team"):
        store.team("Ghost")

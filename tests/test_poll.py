import json

import pytest

from conftest import load
from office_eats import cli, poll
from office_eats.store import Store


@pytest.fixture
def env(monkeypatch, fake_http):
    store = Store(":memory:")
    http = fake_http({"nominatim": load("nominatim_adobe.json"), "overpass": load("overpass_adobe_800m.json")})
    monkeypatch.setattr(cli, "make_http", lambda a: http)
    monkeypatch.setattr(cli, "make_store", lambda: store)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return store


def test_create_vote_tally_close(env, capsys):
    assert cli.main(["poll", "create", "345 Park Ave, San Jose", "--name", "Adobe HQ", "-n", "3"]) == 0
    out, err = capsys.readouterr()
    poll_id = err.split("created poll ")[1].split()[0]
    assert out.startswith("Where should we eat near Adobe HQ?") and len(out.strip().splitlines()) == 4
    assert cli.main(["poll", "vote", poll_id, "ana", "2"]) == 0
    assert cli.main(["poll", "vote", poll_id, "bo", "2"]) == 0
    capsys.readouterr()
    assert cli.main(["poll", "close", poll_id]) == 0
    out = capsys.readouterr().out
    assert "closed" in out.splitlines()[0] and "[2]" in out.splitlines()[2] and "ana, bo" in out
    assert out.strip().splitlines()[-1].startswith("Leading: ")
    assert cli.main(["poll", "vote", poll_id, "cy", "1"]) == 2
    assert "closed" in capsys.readouterr().err


def test_bad_choice_is_a_clean_error(env, capsys):
    pid = env.create_poll("t", [{"id": "a", "name": "A", "url": "u", "walk_min": 1, "blurb": ""}] * 2)
    assert cli.main(["poll", "vote", pid, "ana", "9"]) == 2
    assert "choice must be 1-2" in capsys.readouterr().err


def test_slack_poll_has_one_button_per_open_option(env):
    opts = [{"id": f"node/{i}", "name": f"<!channel> {i}", "url": "https://www.openstreetmap.org/node/1", "walk_min": 3,
             "blurb": "b"} for i in range(3)]
    pid = env.create_poll("Lunch?", opts)
    env.vote(pid, "ana", 2)
    msg = poll.to_slack(env, pid)
    buttons = [b["accessory"] for b in msg["blocks"] if "accessory" in b]
    assert [b["value"] for b in buttons] == [f"{pid}:0", f"{pid}:1", f"{pid}:2"]  # ballot order, not vote order
    assert len({b["action_id"] for b in buttons}) == 3  # Slack requires unique action_ids
    assert "<!channel>" not in json.dumps(msg) and "*1* vote\\n" in json.dumps(msg)
    env.close_poll(pid)
    assert not any("accessory" in b for b in poll.to_slack(env, pid)["blocks"])


def test_parse_vote_value():
    assert poll.parse_vote_value("abc:def:2") == ("abc:def", 2)
    with pytest.raises(ValueError):
        poll.parse_vote_value("abc")

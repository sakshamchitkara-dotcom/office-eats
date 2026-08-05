import pytest

from conftest import load
from office_eats import cli
from office_eats.models import Venue
from office_eats.rotate import choose, rotate, week_key
from office_eats.scoring import Scored
from office_eats.store import Store


def items(*ids):
    return [Scored(Venue(i, i.upper(), 0, 0), 100 - n, []) for n, i in enumerate(ids)]


def test_week_key():
    from datetime import date
    assert week_key(date(2026, 9, 25)) == "2026-W39" and week_key(date(2027, 1, 1)) == "2026-W53"


def test_choose_skips_recent_then_falls_back_to_oldest():
    hist = [{"venue_id": "a"}, {"venue_id": "b"}, {"venue_id": "c"}]  # newest first
    assert choose(items("a", "b", "c", "d"), hist, 4).venue.id == "d"
    assert choose(items("a", "b", "c"), hist, 2).venue.id == "c"  # c is outside the 2-week window
    assert choose(items("a", "b", "c"), hist, 4).venue.id == "c"  # all recent: least recently picked
    assert choose([], hist, 4) is None


@pytest.fixture
def env(monkeypatch, fake_http):
    store = Store(":memory:")
    http = fake_http({"nominatim": load("nominatim_adobe.json"), "overpass": load("overpass_adobe_800m.json")})
    monkeypatch.setattr(cli, "make_store", lambda: store)
    monkeypatch.setattr(cli, "make_http", lambda a: http)
    store.set_team("Platform", location="345 Park Ave, San Jose", office_name="Adobe HQ", tz="America/Los_Angeles", party=6)
    return store, http


def test_rotation_avoids_repeats_across_weeks_and_is_stable_within_a_week(env):
    store, http = env
    picks = [rotate(store, "Platform", http, at=f"2026-09-{d:02d} 12:00")[0]["venue_id"] for d in (7, 14, 21, 28)]
    assert len(set(picks)) == 4
    again, _, _, new = rotate(store, "Platform", http, at="2026-09-29 12:30")  # same ISO week as the 28th
    assert again["venue_id"] == picks[-1] and not new
    rerolled = rotate(store, "Platform", http, at="2026-09-29 12:30", reroll=True)[0]
    assert rerolled["venue_id"] not in picks
    assert [p["week"] for p in store.picks("Platform")] == ["2026-W40", "2026-W39", "2026-W38", "2026-W37"]


def test_rotation_respects_team_diet(env):
    store, http = env
    store.set_team("Platform", diets={"vegan"})
    _, result, chosen, _ = rotate(store, "Platform", http, at="2026-09-21 12:00")
    assert "vegan" in chosen.venue.diets and all("vegan" in s.venue.diets for s in result.items)
    store.set_team("Platform", diets={"vegan", "kosher", "halal"})
    with pytest.raises(ValueError, match="no places match"):
        rotate(store, "Platform", http, at="2026-10-05 12:00")


def test_rotate_cli(env, capsys):
    assert cli.main(["rotate", "Platform", "--at", "2026-09-21 12:00"]) == 0
    first = capsys.readouterr().out
    assert first.startswith("Platform lunch for 2026-W39: ") and "openstreetmap.org" in first
    assert cli.main(["rotate", "Platform", "--at", "2026-09-22 12:00"]) == 0
    assert "already picked this week" in capsys.readouterr().out
    assert cli.main(["rotate", "Platform", "--history"]) == 0
    assert capsys.readouterr().out.startswith("2026-W39  ")


def test_members_prefer_full_coverage_and_never_run_dry(env, capsys):
    store, http = env
    store.set_member("Platform", "ana", {"vegan"})
    store.set_member("Platform", "bo", {"halal"})
    store.set_member("Platform", "cy", set())
    _, result, chosen, _ = rotate(store, "Platform", http, at="2026-09-21 12:00")
    assert {"vegan", "halal"} <= chosen.venue.diets  # one place with an option for both
    assert len(result.items) == 20
    # A mix no single place covers: the old team-wide filter found nothing, coverage still picks the best fit.
    store.set_member("Platform", "dee", {"kosher"})
    assert cli.main(["rotate", "Platform", "--at", "2026-09-28 12:00"]) == 0
    out = capsys.readouterr().out
    # Week 39's vegan+halal pick is now off-limits for repeats, so this week covers fewer people, dee never.
    assert "/3 members with dietary needs; no tagged option for" in out and out.rstrip().endswith("dee")


def test_by_coverage_is_stable():
    from office_eats.rotate import by_coverage
    a, b, c = items("a", "b", "c")
    b.venue.diets = {"vegan", "vegetarian"}
    assert [s.venue.id for s in by_coverage([a, b, c], [{"name": "ana", "diets": ["vegetarian"]}])] == ["b", "a", "c"]


def test_feedback_moves_places_up_and_down(env, capsys):
    store, http = env
    first = rotate(store, "Platform", http, at="2026-09-07 12:00")[0]
    assert cli.main(["feedback", "Platform", "ana", "down"]) == 0
    assert cli.main(["feedback", "Platform", "bo", "down"]) == 0
    assert capsys.readouterr().out.endswith(f"Platform 2026-W37 {first['venue_name']}: 0 up, 2 down\n")
    # Long after the repeat window, the disliked place no longer tops an otherwise identical ranking.
    later = rotate(store, "Platform", http, at="2027-03-01 12:00", avoid_weeks=0)[0]
    assert later["venue_id"] != first["venue_id"]


def test_apply_feedback_caps_and_resorts():
    from office_eats.rotate import apply_feedback
    a, b = items("a", "b")  # scores 100, 99
    out = apply_feedback([a, b], {"a": (0, 9), "b": (1, 0)})
    assert [s.venue.id for s in out] == ["b", "a"] and (a.score, b.score) == (80, 104)
    assert a.reasons == ["team feedback 0 up / 9 down"]

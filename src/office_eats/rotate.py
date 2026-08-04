"""Weekly lunch rotation: one pick per team per ISO week, avoiding places picked in recent weeks."""
from __future__ import annotations

from datetime import date

from .http import Http
from .models import Venue
from .recommend import Query, Result, recommend
from .scoring import Scored
from .store import Store


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def uncovered(venue: Venue, members: list[dict]) -> list[str]:
    """Members with no option at this venue: someone is covered when the venue offers every diet they need."""
    return [m["name"] for m in members if not set(m["diets"]) <= venue.diets]


def by_coverage(items: list[Scored], members: list[dict]) -> list[Scored]:
    """Places with an option for everyone first, then those covering the most people; ranker order breaks ties."""
    return sorted(items, key=lambda s: len(uncovered(s.venue, members)))  # stable sort keeps the ranker's order


def choose(items: list[Scored], history: list[dict], avoid_weeks: int) -> Scored | None:
    """Best-ranked place not picked in the last `avoid_weeks` picks; if all were, the one picked longest ago."""
    if not items:
        return None
    recent = {p["venue_id"] for p in history[:avoid_weeks]}
    if fresh := [s for s in items if s.venue.id not in recent]:
        return fresh[0]
    last_seen = {p["venue_id"]: i for i, p in reversed(list(enumerate(history)))}  # newest index per venue
    return max(items, key=lambda s: last_seen.get(s.venue.id, len(history)))


def rotate(store: Store, team_name: str, http: Http, *, at: str | None = None, avoid_weeks: int = 4,
           reroll: bool = False, routing: str = "none", pool: int = 20) -> tuple[dict, Result, Scored | None, bool]:
    """Returns (pick record, ranked result, chosen item, is_new). Re-running in the same week returns the saved pick."""
    team = store.team(team_name)
    members = [m for m in store.members(team_name) if m["diets"]]
    # Per-person needs are a soft preference over the whole candidate list, so a mixed team never ends up with
    # zero matches; the team-wide diet list stays a hard filter.
    q = Query(team["location"], name=team["office_name"], use_case="lunch", diets=set(team["diets"]), party=team["party"],
              tz=team["tz"], at=at or "now", limit=200 if members else pool, routing=routing, llm="off")
    result = recommend(q, http)
    if members:
        result.items = by_coverage(result.items, members)[:pool]
    week = week_key(result.query.when.date())
    history = [p for p in store.picks(team_name) if p["week"] != week]
    existing = next((p for p in store.picks(team_name) if p["week"] == week), None)
    if existing and not reroll:
        chosen = next((s for s in result.items if s.venue.id == existing["venue_id"]), None)
        return existing, result, chosen, False
    if existing:  # a reroll must not land on the pick it replaces
        history.insert(0, existing)
    chosen = choose(result.items, history, avoid_weeks + bool(existing))
    if chosen is None:
        raise ValueError(f"no places match team {team_name!r} (diet: {', '.join(team['diets']) or 'any'}); "
                         "relax the team's diet or widen the search")
    store.record_pick(team_name, week, chosen.venue.id, chosen.venue.name)
    return {"week": week, "venue_id": chosen.venue.id, "venue_name": chosen.venue.name}, result, chosen, True

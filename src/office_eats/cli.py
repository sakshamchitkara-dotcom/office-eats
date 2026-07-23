"""Command-line entry point."""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

from . import report
from .cache import Cache
from .enrich import DIETS
from .geocode import GeocodeError
from .http import Http, HttpError
from .providers import REGISTRY, ProviderError
from .recommend import Query, recommend
from .routing import ENGINES as ROUTING_ENGINES
from .scoring import PROFILES
from .slack import post_webhook, to_slack
from .store import Store, StoreError

FORMATS = {**report.FORMATS, "slack": lambda r: json.dumps(to_slack(r), indent=2, ensure_ascii=False)}


class DietError(argparse.ArgumentTypeError, ValueError):
    """argparse shows its message for --diet; everywhere else (CSV rows, /eats, team profiles) it is a ValueError."""


def parse_diets(text: str | None) -> set[str]:
    if not text:
        return set()
    out = {d.strip().lower().replace("-", "_") for d in text.split(",") if d.strip()}
    if bad := out - set(DIETS):
        raise DietError(f"unknown diet(s) {sorted(bad)}; choose from {', '.join(DIETS)}")
    return out


def add_query_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-u", "--use-case", choices=sorted(PROFILES), default="lunch")
    p.add_argument("--radius", type=int, help="search radius in metres (default depends on use case)")
    p.add_argument("--max-walk", type=float, help="max walking minutes (also sets radius)")
    p.add_argument("--diet", type=parse_diets, default=set(), help=f"comma list: {', '.join(DIETS)}")
    p.add_argument("--party", type=int, default=0, help="party size")
    p.add_argument("--at", dest="when", help="'now', ISO datetime, or e.g. 'fri 19:00' (local time at the office)")
    p.add_argument("--tz", help="office time zone, e.g. Europe/London (default: looked up from the coordinates)")
    p.add_argument("--open-only", action="store_true", help="drop venues known to be closed at --at")
    p.add_argument("-n", "--limit", type=int, default=8)
    p.add_argument("--provider", choices=sorted(REGISTRY), default="osm")
    p.add_argument("--menus", action="store_true", help="look for menu links on venue websites (robots.txt respected)")
    p.add_argument("--llm", choices=["auto", "on", "off"], default="auto")
    p.add_argument("--routing", choices=ROUTING_ENGINES, default="none",
                   help="walking times: straight-line x1.3 (none), OSRM foot server, or OpenRouteService (ORS_API_KEY)")
    p.add_argument("-f", "--format", choices=sorted(FORMATS), default="table")
    p.add_argument("--no-cache", action="store_true")


def make_query(a: argparse.Namespace, location: str, name: str | None = None) -> Query:
    return Query(location=location, name=name, use_case=a.use_case, radius_m=a.radius, max_walk=a.max_walk,
                 diets=a.diet, party=a.party, at=a.when, tz=a.tz, open_only=a.open_only, limit=a.limit,
                 provider=a.provider, menus=a.menus, llm=a.llm, routing=a.routing)


def make_http(a: argparse.Namespace) -> Http:
    return Http(cache=None if a.no_cache else Cache())


def cmd_recommend(a: argparse.Namespace) -> int:
    result = recommend(make_query(a, a.location, a.name), make_http(a))
    if a.slack:
        post_webhook(to_slack(result))
        print("posted to Slack", file=sys.stderr)
    text = FORMATS[a.format](result)
    if a.out:
        Path(a.out).write_text(text + "\n")
        print(f"wrote {a.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def read_offices(path: str) -> list[dict]:
    """CSV with a `name` column and either `address` or `lat`+`lon`. Optional per-row: use_case, diet, party."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = [{k.strip().lower(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)]
    offices = []
    for i, row in enumerate(rows, 2):
        loc = row.get("address") or (f"{row['lat']},{row['lon']}" if row.get("lat") and row.get("lon") else "")
        if not loc:
            raise ValueError(f"{path}:{i}: need an address or lat+lon")
        offices.append({**row, "location": loc, "name": row.get("name") or loc})
    return offices


def cmd_batch(a: argparse.Namespace) -> int:
    http, failures = make_http(a), 0
    out_dir = Path(a.out_dir) if a.out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    ext = {"table": "txt", "md": "md", "html": "html", "map": "html", "json": "json", "slack": "json"}[a.format]
    for office in read_offices(a.csv):
        q = make_query(a, office["location"], office["name"])
        q.use_case = office.get("use_case") or q.use_case
        try:  # a bad diet or party in one row is that row's failure, not the whole batch's
            q.diets = parse_diets(office.get("diet")) or q.diets
            q.party = int(office.get("party") or q.party)
            text = FORMATS[a.format](recommend(q, http))
        except (GeocodeError, ProviderError, HttpError, ValueError) as e:
            failures += 1
            print(f"office-eats: {office['name']}: {e}", file=sys.stderr)
            continue
        if out_dir:
            path = out_dir / f"{re.sub(r'[^a-z0-9]+', '-', office['name'].lower()).strip('-') or 'office'}.{ext}"
            path.write_text(text + "\n")
            print(f"wrote {path}", file=sys.stderr)
        else:
            print(text, end="\n\n")
    return 1 if failures else 0


def make_store() -> Store:
    return Store()


def cmd_poll(a: argparse.Namespace) -> int:
    from . import poll  # poll imports recommend/slack; keep startup light for the other commands

    store = make_store()
    if a.poll_cmd == "create":
        r = recommend(make_query(a, a.location, a.name), make_http(a))
        if len(r.items) < 2:
            raise ValueError("need at least 2 matching places for a poll; relax the filters")
        poll_id = poll.create_from_result(store, r, a.title)
        print(f"created poll {poll_id}", file=sys.stderr)
    else:
        poll_id = a.poll_id
        if a.poll_cmd == "vote":
            store.vote(poll_id, a.voter, a.choice - 1)
        elif a.poll_cmd == "close":
            store.close_poll(poll_id)
    if getattr(a, "slack", False):
        post_webhook(poll.to_slack(store, poll_id))
        print("posted to Slack", file=sys.stderr)
    print(json.dumps(poll.to_slack(store, poll_id), indent=2, ensure_ascii=False) if a.poll_format == "slack"
          else poll.to_text(store, poll_id))
    return 0


def _team_line(t: dict) -> str:
    return (f"{t['name']}: {t['office_name'] or t['location']} ({t['location']}) · diet: {', '.join(t['diets']) or 'any'}"
            f" · party: {t['party'] or '-'} · tz: {t['tz'] or 'auto'}")


def cmd_team(a: argparse.Namespace) -> int:
    store = make_store()
    if a.team_cmd == "set":
        t = store.set_team(a.team, location=a.office, office_name=a.office_name, party=a.party, tz=a.tz,
                           diets=None if a.diet is None else parse_diets(a.diet))
        print(_team_line(t))
    elif a.team_cmd == "show":
        print(_team_line(store.team(a.team)))
    else:
        print("\n".join(_team_line(t) for t in store.teams()) or "(no teams yet)")
    return 0


def cmd_rotate(a: argparse.Namespace) -> int:
    from .models import osm_link
    from .rotate import rotate

    store = make_store()
    if a.history:
        print("\n".join(f"{p['week']}  {p['venue_name']}" for p in store.picks(a.team)) or "(no picks yet)")
        return 0
    pick, _, chosen, new = rotate(store, a.team, make_http(a), at=a.when, avoid_weeks=a.avoid_weeks, reroll=a.reroll,
                                  routing=a.routing)
    lines = [f"{a.team} lunch for {pick['week']}: {pick['venue_name']}" + ("" if new else " (already picked this week; --reroll to change)")]
    if chosen:
        v = chosen.venue
        lines += [f"  {v.walk_min:.0f} min walk · {', '.join(v.cuisine[:2]) or v.kind} · {chosen.blurb}", f"  {osm_link(v)}"]
    text = "\n".join(lines)
    if a.slack:
        from .slack import esc
        post_webhook({"text": text, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": esc(text)[:3000]}}]})
        print("posted to Slack", file=sys.stderr)
    print(text)
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    from .server import serve  # imports cli helpers, so keep it lazy

    serve(a.host, a.port, a.insecure)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="office-eats", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("recommend", help="recommend places near one office")
    r.add_argument("location", help="address, company name, or 'lat,lon'")
    r.add_argument("--name", help="display name for the office")
    r.add_argument("-o", "--out", help="write to file instead of stdout")
    r.add_argument("--slack", action="store_true", help="also post to SLACK_WEBHOOK_URL")
    add_query_args(r)
    r.set_defaults(func=cmd_recommend)

    b = sub.add_parser("batch", help="recommend places for every office in a CSV")
    b.add_argument("csv", help="CSV with name + address (or lat, lon); optional use_case, diet, party columns")
    b.add_argument("--out-dir", help="write one report per office into this directory")
    add_query_args(b)
    b.set_defaults(func=cmd_batch)

    pl = sub.add_parser("poll", help="team lunch polls: create from a shortlist, vote, tally")
    psub = pl.add_subparsers(dest="poll_cmd", required=True)
    pc = psub.add_parser("create", help="shortlist places near an office and open a poll")
    pc.add_argument("location", help="address, company name, or 'lat,lon'")
    pc.add_argument("--name", help="display name for the office")
    pc.add_argument("--title", help="poll question")
    pc.add_argument("--slack", action="store_true", help="post the poll (with vote buttons) to SLACK_WEBHOOK_URL")
    add_query_args(pc)
    pc.set_defaults(limit=4)
    pv = psub.add_parser("vote", help="record a vote (voting again changes it)")
    pv.add_argument("poll_id")
    pv.add_argument("voter")
    pv.add_argument("choice", type=int, help="option number, starting at 1")
    for name, help_ in (("tally", "show the current tally"), ("close", "close the poll and show the result")):
        psub.add_parser(name, help=help_).add_argument("poll_id")
    for p_ in psub.choices.values():
        p_.add_argument("--poll-format", choices=["text", "slack"], default="text", help="print the poll as text or Slack JSON")
    pl.set_defaults(func=cmd_poll)

    t = sub.add_parser("team", help="saved team profiles: office, dietary needs, party size")
    tsub = t.add_subparsers(dest="team_cmd", required=True)
    ts = tsub.add_parser("set", help="create or update a team")
    ts.add_argument("team")
    ts.add_argument("--office", help="office address, company name, or 'lat,lon'")
    ts.add_argument("--office-name", help="display name for the office")
    ts.add_argument("--diet", help=f"team dietary needs, every pick must meet all of them ({', '.join(DIETS)}); '' clears")
    ts.add_argument("--party", type=int, help="usual party size")
    ts.add_argument("--tz", help="office time zone (default: looked up)")
    tsub.add_parser("show", help="show one team").add_argument("team")
    tsub.add_parser("list", help="list teams")
    t.set_defaults(func=cmd_team)

    ro = sub.add_parser("rotate", help="pick this week's team lunch, avoiding recent repeats")
    ro.add_argument("team")
    ro.add_argument("--avoid-weeks", type=int, default=4, help="skip places picked in this many previous weeks (default 4)")
    ro.add_argument("--at", dest="when", help="lunch time to check opening hours against (default: now, office time)")
    ro.add_argument("--reroll", action="store_true", help="replace this week's pick")
    ro.add_argument("--history", action="store_true", help="list past picks and exit")
    ro.add_argument("--routing", choices=ROUTING_ENGINES, default="none")
    ro.add_argument("--slack", action="store_true", help="also post the pick to SLACK_WEBHOOK_URL")
    ro.add_argument("--no-cache", action="store_true")
    ro.set_defaults(func=cmd_rotate)

    s = sub.add_parser("serve", help="run the Slack slash-command endpoint")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    s.add_argument("--insecure", action="store_true", help="skip Slack signature checks (local testing only)")
    s.set_defaults(func=cmd_serve)

    c = sub.add_parser("clear-cache", help="delete cached API responses")
    c.set_defaults(func=lambda a: print(f"removed {Cache().clear()} entries") or 0)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.func(a)
    except (GeocodeError, ProviderError, HttpError, StoreError, ValueError) as e:
        print(f"office-eats: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

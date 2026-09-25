"""Command-line entry point."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import report
from .cache import Cache
from .enrich import DIETS
from .geocode import GeocodeError
from .http import Http, HttpError
from .providers import REGISTRY, ProviderError
from .recommend import Query, recommend
from .scoring import PROFILES

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_when(text: str | None, now: datetime | None = None) -> datetime | None:
    """'now', ISO ('2026-09-22 12:30'), or '<day> HH:MM' (next occurrence, e.g. 'fri 19:00')."""
    if not text:
        return None
    now = now or datetime.now()
    t = text.strip().lower()
    if t == "now":
        return now.replace(second=0, microsecond=0)
    parts = t.split()
    if len(parts) == 2 and parts[0][:3] in DAY_NAMES:
        hh, mm = map(int, parts[1].split(":"))
        ahead = (DAY_NAMES.index(parts[0][:3]) - now.weekday()) % 7
        when = (now + timedelta(days=ahead)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        return when if when >= now else when + timedelta(days=7)
    return datetime.fromisoformat(text)


def parse_diets(text: str | None) -> set[str]:
    if not text:
        return set()
    out = {d.strip().lower().replace("-", "_") for d in text.split(",") if d.strip()}
    if bad := out - set(DIETS):
        raise argparse.ArgumentTypeError(f"unknown diet(s) {sorted(bad)}; choose from {', '.join(DIETS)}")
    return out


def add_query_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("-u", "--use-case", choices=sorted(PROFILES), default="lunch")
    p.add_argument("--radius", type=int, help="search radius in metres (default depends on use case)")
    p.add_argument("--max-walk", type=float, help="max walking minutes (also sets radius)")
    p.add_argument("--diet", type=parse_diets, default=set(), help=f"comma list: {', '.join(DIETS)}")
    p.add_argument("--party", type=int, default=0, help="party size")
    p.add_argument("--at", dest="when", help="'now', ISO datetime, or e.g. 'fri 19:00' (local time at the office)")
    p.add_argument("--open-only", action="store_true", help="drop venues known to be closed at --at")
    p.add_argument("-n", "--limit", type=int, default=8)
    p.add_argument("--provider", choices=sorted(REGISTRY), default="osm")
    p.add_argument("--menus", action="store_true", help="look for menu links on venue websites (robots.txt respected)")
    p.add_argument("--llm", choices=["auto", "on", "off"], default="auto")
    p.add_argument("-f", "--format", choices=sorted(report.FORMATS), default="table")
    p.add_argument("--no-cache", action="store_true")


def make_query(a: argparse.Namespace, location: str, name: str | None = None) -> Query:
    return Query(location=location, name=name, use_case=a.use_case, radius_m=a.radius, max_walk=a.max_walk,
                 diets=a.diet, party=a.party, when=parse_when(a.when), open_only=a.open_only, limit=a.limit,
                 provider=a.provider, menus=a.menus, llm=a.llm)


def make_http(a: argparse.Namespace) -> Http:
    return Http(cache=None if a.no_cache else Cache())


def cmd_recommend(a: argparse.Namespace) -> int:
    result = recommend(make_query(a, a.location, a.name), make_http(a))
    text = report.FORMATS[a.format](result)
    if a.out:
        Path(a.out).write_text(text + "\n")
        print(f"wrote {a.out}", file=sys.stderr)
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="office-eats", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("recommend", help="recommend places near one office")
    r.add_argument("location", help="address, company name, or 'lat,lon'")
    r.add_argument("--name", help="display name for the office")
    r.add_argument("-o", "--out", help="write to file instead of stdout")
    add_query_args(r)
    r.set_defaults(func=cmd_recommend)

    c = sub.add_parser("clear-cache", help="delete cached API responses")
    c.set_defaults(func=lambda a: print(f"removed {Cache().clear()} entries") or 0)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.func(a)
    except (GeocodeError, ProviderError, HttpError, ValueError) as e:
        print(f"office-eats: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

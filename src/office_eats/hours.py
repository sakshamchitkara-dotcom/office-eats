"""A pragmatic subset of the OSM opening_hours grammar.

Handles weekday ranges/lists, the nth weekday of a month (Th[4], Mo[-1]), dates and months ("Dec 25 off",
"Dec 24 10:00-16:00", "Dec 24-Jan 02", "Aug off", "Nov Th[4] off"), multiple time spans, overnight spans
(e.g. 16:00-01:30 or 11:00-27:00), 'off'/'closed', and 24/7. Rules apply in order, a later one replacing an earlier
one on the days both cover (',' adds to it instead). Anything fancier (PH, SH, week numbers, sunrise, years) is skipped;
if nothing parses we return None = unknown.
"""
from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_DAY = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:\[-?[1-5]\])?"
_MON = "(?:" + "|".join(MONTHS) + ")"
_DATE = rf"{_MON}(?:\s+\d{{1,2}}(?!:))?"  # "Dec" or "Dec 25"; (?!:) keeps "Dec 10:00-..." from reading 10 as a day
_DATES = rf"{_DATE}(?:\s*-\s*(?:{_DATE}|\d{{1,2}}(?!:)))?"  # "Dec 24-26", "Dec 24-Jan 02", "Jun-Aug"
_TIME = r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\+?"
_RULE = re.compile(
    rf"(?:(?P<dates>{_DATES}(?:\s*,\s*{_DATES})*)\s*:?\s*)?"
    rf"(?P<days>{_DAY}(?:\s*[-,]\s*{_DAY})*)?\s*(?P<times>off|closed|{_TIME}(?:\s*,\s*{_TIME})*)"
)

Span = tuple[int, int]  # (start_min, end_min) from midnight; end may exceed 1440 for overnight spans


@dataclass
class Rule:
    dates: list[tuple[int, int, int, int]] | None  # [(month, day, month, day)] inclusive; None = any date
    days: list[tuple[int, int | None]] | None  # [(weekday, nth of month or None)]; None = every day
    spans: list[Span]
    additive: bool

    def matches(self, d: date) -> bool:
        if self.dates is not None and not any(_in_range(d, *r) for r in self.dates):
            return False
        return self.days is None or any(d.weekday() == wd and (n is None or _nth(d) == n or _nth_last(d) == n) for wd, n in self.days)


def _nth(d: date) -> int:
    return (d.day - 1) // 7 + 1


def _nth_last(d: date) -> int:
    return -((calendar.monthrange(d.year, d.month)[1] - d.day) // 7 + 1)


def _in_range(d: date, m1: int, d1: int, m2: int, d2: int) -> bool:
    key = (d.month, d.day)
    return (m1, d1) <= key <= (m2, d2) if (m1, d1) <= (m2, d2) else key >= (m1, d1) or key <= (m2, d2)  # wraps the new year


def _one_date(text: str, end: bool) -> tuple[int, int]:
    mon, _, day = text.strip().partition(" ")
    m = MONTHS.index(mon) + 1
    return m, int(day) if day.strip() else (31 if end else 1)


def _dates(spec: str | None) -> list[tuple[int, int, int, int]] | None:
    if not spec:
        return None
    out = []
    for part in re.split(r"\s*,\s*", spec.strip()):
        a, _, b = (s.strip() for s in part.partition("-"))
        m1, d1 = _one_date(a, end=False)
        if not b:
            m2, d2 = _one_date(a, end=True)
        elif b.isdigit():  # "Dec 24-26"
            m2, d2 = m1, int(b)
        else:
            m2, d2 = _one_date(b, end=True)
        out.append((m1, d1, m2, d2))
    return out


def _days(spec: str | None) -> list[tuple[int, int | None]] | None:
    if not spec:
        return None
    out: list[tuple[int, int | None]] = []
    for part in spec.replace(" ", "").split(","):
        if not (fm := re.fullmatch(r"(\w\w)(?:\[(-?\d)\])?(?:-(\w\w))?", part)):
            raise ValueError(part)  # e.g. "Mo-Fr[2]": not a form we read
        a, nth, b = fm.groups()
        i = DAYS.index(a)
        if not b:
            out.append((i, int(nth) if nth else None))
            continue
        j = DAYS.index(b)
        out.extend(((i + k) % 7, None) for k in range(((j - i) % 7) + 1))  # wraps, e.g. Su-Th
    return out


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def parse(text: str | None) -> list[Rule] | None:
    if not text:
        return None
    text = text.strip()
    if text == "24/7":
        return [Rule(None, None, [(0, 1440)], False)]
    rules: list[Rule] = []
    prev_end = 0
    for m in _RULE.finditer(text):
        # Text between rules must be separators only. Anything else is a selector we don't understand
        # (PH, SH, week numbers, years), and the rule is skipped: "PH off" must not close every day.
        between, prev_end = text[prev_end: m.start()], m.end()
        if between.strip(" ,;"):
            continue
        spans = []
        if m["times"] not in ("off", "closed"):
            for span in m["times"].split(","):
                a, b = (s.strip().rstrip("+") for s in span.split("-"))
                start, end = _mins(a), _mins(b)
                if end <= start:
                    end += 1440  # overnight
                spans.append((start, end))
        additive = text[: m.start()].rstrip().endswith(",")  # ',' adds to earlier rules, ';' overrides
        try:
            rules.append(Rule(_dates(m["dates"]), _days(m["days"]), spans, additive))
        except ValueError:
            continue
    return rules or None


def spans_on(rules: list[Rule], d: date) -> list[Span]:
    """Opening spans for one calendar date: each matching rule replaces the earlier ones (or adds to them after ',')."""
    out: list[Span] = []
    for r in rules:
        if r.matches(d):
            out = (out if r.additive else []) + r.spans
    return out


def is_open(text: str | None, when: datetime) -> bool | None:
    """True/False if we can tell from opening_hours, None if unknown."""
    rules = parse(text)
    if rules is None:
        return None
    day, t = when.date(), when.hour * 60 + when.minute
    if any(s <= t < e for s, e in spans_on(rules, day)):
        return True
    return any(e > 1440 and t < e - 1440 for _, e in spans_on(rules, day - timedelta(days=1)))

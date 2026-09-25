"""A pragmatic subset of the OSM opening_hours grammar.

Handles weekday ranges/lists, multiple time spans, overnight spans (e.g. 16:00-01:30
or 11:00-27:00), 'off'/'closed', and 24/7. Anything fancier (PH, month ranges,
sunrise, week numbers) is skipped; if nothing parses we return None = unknown.
"""
from __future__ import annotations

import re
from datetime import datetime

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_DAY = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
_TIME = r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\+?"
_RULE = re.compile(
    rf"(?P<days>{_DAY}(?:\s*[-,]\s*{_DAY})*)?\s*(?P<times>off|closed|{_TIME}(?:\s*,\s*{_TIME})*)"
)

Schedule = dict[int, list[tuple[int, int]]]  # weekday -> [(start_min, end_min)], end may exceed 1440


def _days(spec: str | None) -> list[int]:
    if not spec:
        return list(range(7))
    out: list[int] = []
    for part in spec.replace(" ", "").split(","):
        a, _, b = part.partition("-")
        i = DAYS.index(a)
        if not b:
            out.append(i)
            continue
        j = DAYS.index(b)
        out.extend((i + k) % 7 for k in range(((j - i) % 7) + 1))  # wraps, e.g. Su-Th
    return out


def _mins(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def parse(text: str | None) -> Schedule | None:
    if not text:
        return None
    text = text.strip()
    if text == "24/7":
        return {d: [(0, 1440)] for d in range(7)}
    sched: Schedule = {}
    prev_end = 0
    for m in _RULE.finditer(text):
        # Text between rules must be separators only. Anything else is a selector we don't understand
        # (PH, "Dec 25", "Aug", week numbers), and the rule is skipped: "Dec 25 off" must not close every day.
        between, prev_end = text[prev_end: m.start()], m.end()
        if between.strip(" ,;"):
            continue
        additive = text[: m.start()].rstrip().endswith(",")  # ',' adds to earlier rules, ';' overrides
        spans = []
        if m["times"] not in ("off", "closed"):
            for span in m["times"].split(","):
                a, b = (s.strip().rstrip("+") for s in span.split("-"))
                start, end = _mins(a), _mins(b)
                if end <= start:
                    end += 1440  # overnight
                spans.append((start, end))
        for d in _days(m["days"]):
            sched[d] = (sched.get(d, []) if additive else []) + spans
    return sched or None


def is_open(text: str | None, when: datetime) -> bool | None:
    """True/False if we can tell from opening_hours, None if unknown."""
    sched = parse(text)
    if sched is None:
        return None
    d, t = when.weekday(), when.hour * 60 + when.minute
    if any(s <= t < e for s, e in sched.get(d, [])):
        return True
    prev = (d - 1) % 7
    return any(e > 1440 and t < e - 1440 for _, e in sched.get(prev, []))

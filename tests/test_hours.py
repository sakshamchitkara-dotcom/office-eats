from datetime import datetime

import pytest

from conftest import load
from office_eats.hours import is_open, parse, spans_on

# 2026-09-21 is a Monday
MON, FRI, SAT, SUN = 21, 25, 26, 27


def at(day, hh, mm=0):
    return datetime(2026, 9, day, hh, mm)


@pytest.mark.parametrize("text,when,expected", [
    ("Mo-Fr 11:00-14:00", at(MON, 12), True),
    ("Mo-Fr 11:00-14:00", at(SAT, 12), False),
    ("Mo-Fr 11:00-14:00", at(MON, 14), False),
    ("24/7", at(SUN, 3), True),
    ("Mo,Su off; Tu-Th 11:30-21:00; Fr 11:30-22:00", at(MON, 12), False),
    ("Mo,Su off; Tu-Th 11:30-21:00; Fr 11:30-22:00", at(FRI, 21, 30), True),
    ("Su-Th 16:00-23:00, Fr-Sa 16:00-00:00", at(SAT, 23, 30), True),  # ends at midnight
    ("Su-Th 11:00-24:00; Fr-Sa 11:00-27:00", at(SUN, 2), True),  # Sat night spill-over
    ("Mo-Sa 07:00-16:00, Su 07:00-12:00", at(SUN, 11), True),
    ("Tu-Fr 17:00-22:00; Sa-Su 10:00-13:00,17:00-22:00", at(SUN, 15), False),
    ("Tu-Fr 17:00-22:00; Sa-Su 10:00-13:00,17:00-22:00", at(SUN, 18), True),
    ("08:00-14:00", at(SUN, 9), True),
    ("sunrise-sunset", at(MON, 12), None),
    (None, at(MON, 12), None),
])
def test_is_open(text, when, expected):
    assert is_open(text, when) is expected


def test_ph_rules_ignored():
    assert spans_on(parse("Mo-Fr 09:00-17:00; PH off"), datetime(2026, 12, 25).date()) == [(540, 1020)]


@pytest.mark.parametrize("text", ["Mo-Su 11:00-22:00; Dec 25 off", "Mo-Su 11:00-22:00; Jan 01 off", "Mo-Su 11:00-22:00; Aug off",
                                  "Mo-Su 11:00-22:00; Su,PH off"])
def test_date_rules_do_not_close_every_day(text):
    assert is_open(text, at(MON, 12)) is True


# Real values from Overpass responses cached on 2026-09-25 (San Jose and San Francisco offices).
XMAS = "Su-Mo 10:00-20:00; Tu-Sa 10:00-21:00; Nov Th[4] off; Dec 24 10:00-16:00; Dec 25 off; Dec 31 10:00-25:00"


@pytest.mark.parametrize("text,when,expected", [
    ("Mo-Su 11:00-22:00; Dec 25 off", datetime(2026, 12, 25, 12), False),
    ("Mo-Su 11:00-22:00; Dec 25 off", datetime(2026, 12, 26, 12), True),
    ("Mo off; Tu-Su 08:00-14:00; Dec 25 off", datetime(2026, 12, 24, 12), True),
    ("Mo off; Tu-Su 08:00-14:00; Dec 25 off", datetime(2026, 12, 25, 12), False),
    ("Mo-Fr 08:00-14:00; Sa-Su 08:00-15:00; Jan 1 off; Dec 31 08:00-13:00", datetime(2027, 1, 1, 9), False),
    ("Mo-Fr 08:00-14:00; Sa-Su 08:00-15:00; Jan 1 off; Dec 31 08:00-13:00", datetime(2026, 12, 31, 13, 30), False),
    ("Mo-Fr 08:00-14:00; Sa-Su 08:00-15:00; Jan 1 off; Dec 31 08:00-13:00", datetime(2026, 12, 31, 12), True),
    (XMAS, datetime(2026, 11, 26, 12), False),  # Thanksgiving: 4th Thursday of November
    (XMAS, datetime(2026, 11, 19, 12), True),  # 3rd Thursday
    (XMAS, datetime(2026, 12, 24, 17), False),  # Christmas Eve closes at 16:00
    (XMAS, datetime(2026, 12, 23, 17), True),
    (XMAS, datetime(2027, 1, 1, 0, 30), True),  # New Year's Eve runs to 01:00
    (XMAS, datetime(2027, 1, 1, 1, 30), False),
    ("Mo-Su 11:00-22:00; Aug off", datetime(2026, 8, 3, 12), False),
    ("Mo-Su 11:00-22:00; Dec 24-Jan 02 off", datetime(2027, 1, 2, 12), False),
    ("Mo-Su 11:00-22:00; Dec 24-Jan 02 off", datetime(2027, 1, 3, 12), True),
    ("Mo-Su 11:00-22:00; Dec 24-26 off", datetime(2026, 12, 26, 12), False),
    ("Mo-Fr 11:00-22:00; Mo[-1] off", datetime(2026, 9, 28, 12), False),  # last Monday of September
    ("Mo-Fr 11:00-22:00; Mo[-1] off", datetime(2026, 9, 21, 12), True),
    ("Dec 25 off; Mo-Su 11:00-22:00", datetime(2026, 12, 25, 12), True),  # a later rule wins
])
def test_date_rules(text, when, expected):
    assert is_open(text, when) is expected


@pytest.mark.parametrize("text,when,expected", [
    ("Mo-Su,PH 16:00-02:00", at(SAT, 1), True),  # real San Francisco values that used to read as unknown
    ("Mo-Su, PH 06:30-23:00", at(MON, 23, 30), False),
    ("PH,Mo-Su 11:00-22:00", at(SUN, 12), True),
    ("Mo-Sa 11:30-13:30,17:30-20:30; PH,Su off", at(SUN, 12), False),
    ("Mo-Fr 08:00-15:00, PH closed", at(MON, 9), True),  # PH not next to a weekday: that rule is skipped, not applied daily
])
def test_ph_listed_with_weekdays(text, when, expected):
    assert is_open(text, when) is expected


def test_every_fixture_value_is_handled():
    tags = [e["tags"].get("opening_hours") for e in load("overpass_adobe_800m.json")["elements"]]
    for t in filter(None, tags):
        assert parse(t), t

from datetime import datetime

import pytest

from conftest import load
from office_eats.hours import is_open, parse

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
    assert parse("Mo-Fr 09:00-17:00; PH off")[0] == [(540, 1020)]


@pytest.mark.parametrize("text", ["Mo-Su 11:00-22:00; Dec 25 off", "Mo-Su 11:00-22:00; Jan 01 off", "Mo-Su 11:00-22:00; Aug off",
                                  "Mo-Su 11:00-22:00; Su,PH off"])
def test_date_rules_do_not_close_every_day(text):
    assert is_open(text, at(MON, 12)) is True


def test_every_fixture_value_is_handled():
    tags = [e["tags"].get("opening_hours") for e in load("overpass_adobe_800m.json")["elements"]]
    for t in filter(None, tags):
        assert parse(t), t

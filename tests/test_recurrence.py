"""Recurrence date arithmetic.

Pure functions, so these are cheap and can be exhaustive. Date maths is where
this feature would fail quietly, so the awkward cases are covered deliberately:
month-end clamping, leap years, and finishing long after the scheduled date.
"""

from datetime import date

import pytest

from gtd.recurrence import (
    RepeatDays,
    RepeatFrom,
    RepeatUnit,
    Rule,
    describe,
    format_days,
    next_occurrence,
    parse_days,
)


def interval(every, unit, anchor=RepeatFrom.SCHEDULE):
    return Rule(every=every, unit=unit, anchor=anchor)


def weekly_days(*days):
    return Rule(days=frozenset(str(d) for d in days))


WORKING_WEEK = (
    RepeatDays.MONDAY, RepeatDays.TUESDAY, RepeatDays.WEDNESDAY,
    RepeatDays.THURSDAY, RepeatDays.FRIDAY,
)


# ── Intervals ────────────────────────────────────────────────────────────────


def test_daily_advances_one_day():
    rule = interval(1, RepeatUnit.DAY)
    assert next_occurrence(rule, anchor=date(2026, 9, 4), today=date(2026, 9, 4)) == date(2026, 9, 5)


def test_every_three_months():
    rule = interval(3, RepeatUnit.MONTH)
    assert next_occurrence(rule, anchor=date(2026, 1, 15), today=date(2026, 1, 15)) == date(2026, 4, 15)


def test_month_end_clamps_instead_of_drifting():
    """31 January plus a month is 28 February, not 3 March. Rolling over would
    push the task a few days later on every single repeat."""
    rule = interval(1, RepeatUnit.MONTH)
    assert next_occurrence(rule, anchor=date(2026, 1, 31), today=date(2026, 1, 31)) == date(2026, 2, 28)


def test_month_end_clamping_uses_a_leap_year_february():
    rule = interval(1, RepeatUnit.MONTH)
    assert next_occurrence(rule, anchor=date(2028, 1, 31), today=date(2028, 1, 31)) == date(2028, 2, 29)


def test_yearly_across_a_leap_day():
    rule = interval(1, RepeatUnit.YEAR)
    assert next_occurrence(rule, anchor=date(2028, 2, 29), today=date(2028, 2, 29)) == date(2029, 2, 28)


def test_weekly():
    rule = interval(2, RepeatUnit.WEEK)
    assert next_occurrence(rule, anchor=date(2026, 9, 4), today=date(2026, 9, 4)) == date(2026, 9, 18)


# ── No backfill ──────────────────────────────────────────────────────────────


def test_finishing_late_produces_one_occurrence_not_a_backlog():
    """Three days late on a daily task must not generate three items."""
    rule = interval(1, RepeatUnit.DAY)
    result = next_occurrence(rule, anchor=date(2026, 9, 1), today=date(2026, 9, 4))

    assert result == date(2026, 9, 5)


def test_a_long_absence_still_lands_in_the_future():
    rule = interval(1, RepeatUnit.WEEK)
    result = next_occurrence(rule, anchor=date(2026, 1, 1), today=date(2026, 9, 4))

    assert result > date(2026, 9, 4)


def test_the_next_occurrence_is_never_today():
    """Otherwise completing a daily task would immediately re-present it."""
    rule = interval(1, RepeatUnit.DAY)
    assert next_occurrence(rule, anchor=date(2026, 9, 3), today=date(2026, 9, 4)) == date(2026, 9, 5)


# ── Anchors ──────────────────────────────────────────────────────────────────


def test_schedule_anchor_keeps_the_original_cadence():
    """Due Monday, done Wednesday, weekly: next is the following Monday."""
    rule = interval(1, RepeatUnit.WEEK, anchor=RepeatFrom.SCHEDULE)
    monday, wednesday = date(2026, 9, 7), date(2026, 9, 9)

    assert next_occurrence(rule, anchor=monday, today=wednesday) == date(2026, 9, 14)


def test_completion_anchor_restarts_the_clock():
    """Same task anchored to completion lands a week after it was *done*."""
    rule = interval(1, RepeatUnit.WEEK, anchor=RepeatFrom.COMPLETION)
    wednesday = date(2026, 9, 9)

    assert next_occurrence(rule, anchor=wednesday, today=wednesday) == date(2026, 9, 16)


# ── Days of week ─────────────────────────────────────────────────────────────


def test_weekdays_skips_the_weekend():
    """Friday's next weekday occurrence is Monday."""
    rule = weekly_days(*WORKING_WEEK)
    friday = date(2026, 9, 4)
    assert friday.weekday() == 4

    assert next_occurrence(rule, anchor=friday, today=friday) == date(2026, 9, 7)


def test_weekdays_midweek_is_tomorrow():
    rule = weekly_days(*WORKING_WEEK)
    tuesday = date(2026, 9, 8)

    assert next_occurrence(rule, anchor=tuesday, today=tuesday) == date(2026, 9, 9)


def test_saturday_only_repeats_weekly():
    rule = weekly_days(RepeatDays.SATURDAY)
    saturday = date(2026, 9, 5)
    assert saturday.weekday() == 5

    assert next_occurrence(rule, anchor=saturday, today=saturday) == date(2026, 9, 12)


def test_saturday_and_sunday_together():
    rule = weekly_days(RepeatDays.SATURDAY, RepeatDays.SUNDAY)
    saturday = date(2026, 9, 5)

    assert next_occurrence(rule, anchor=saturday, today=saturday) == date(2026, 9, 6)


def test_all_seven_days_is_every_day():
    rule = weekly_days(*RepeatDays)
    friday = date(2026, 9, 4)

    assert next_occurrence(rule, anchor=friday, today=friday) == date(2026, 9, 5)


def test_day_rules_do_not_backfill_after_a_long_gap():
    rule = weekly_days(*WORKING_WEEK)
    result = next_occurrence(rule, anchor=date(2026, 1, 1), today=date(2026, 9, 4))

    assert result > date(2026, 9, 4)
    assert result.weekday() in {0, 1, 2, 3, 4}


# ── Storage of the day set ───────────────────────────────────────────────────


def test_day_sets_round_trip_in_day_order():
    stored = format_days({RepeatDays.SUNDAY, RepeatDays.WEDNESDAY, RepeatDays.MONDAY})

    assert stored == "mon,wed,sun", "stored in week order, not set order"
    assert parse_days(stored) == {"mon", "wed", "sun"}


def test_unknown_or_blank_day_values_are_ignored():
    assert parse_days("mon,,nonsense, sat ") == {"mon", "sat"}
    assert parse_days("") == frozenset()
    assert parse_days(None) == frozenset()
    assert format_days(set()) is None


# ── Guards ───────────────────────────────────────────────────────────────────


def test_a_non_repeating_rule_returns_nothing():
    assert next_occurrence(Rule(), anchor=date(2026, 9, 4), today=date(2026, 9, 4)) is None


def test_a_zero_interval_is_rejected_rather_than_looping():
    with pytest.raises(Exception):
        next_occurrence(interval(0, RepeatUnit.DAY), anchor=date(2026, 9, 4), today=date(2026, 9, 4))


def test_an_unknown_unit_is_rejected():
    with pytest.raises(Exception):
        next_occurrence(interval(1, "fortnight"), anchor=date(2026, 9, 4), today=date(2026, 9, 4))


# ── Descriptions ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rule,expected",
    [
        (interval(1, RepeatUnit.DAY), "every day"),
        (interval(3, RepeatUnit.MONTH), "every 3 months"),
        (interval(5, RepeatUnit.DAY, RepeatFrom.COMPLETION), "every 5 days from completion"),
        (weekly_days(*WORKING_WEEK), "every weekday"),
        (weekly_days(RepeatDays.WEDNESDAY), "every Wednesday"),
        (weekly_days(RepeatDays.SATURDAY, RepeatDays.SUNDAY), "every weekend"),
        (weekly_days(RepeatDays.MONDAY, RepeatDays.WEDNESDAY, RepeatDays.FRIDAY),
         "every Monday, Wednesday and Friday"),
        (weekly_days(*RepeatDays), "every day"),
        (Rule(), "does not repeat"),
    ],
)
def test_rules_read_back_in_english(rule, expected):
    assert describe(rule) == expected

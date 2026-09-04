"""When a repeating task comes back.

Pure date arithmetic, deliberately separate from the store: this is where the
bugs live, and it should be testable without a database.

Two ways to repeat, because neither covers the other:

- **Interval** — every N days / weeks / months / years. "Change the furnace
  filter every 3 months."
- **Days of week** — any combination of the seven days. Individual days rather
  than a weekday/weekend grouping, because real schedules are not tidy: the bins
  go out on a Wednesday.

And two anchors, which matter when you finish late:

- `schedule` — the next occurrence follows the *planned* date. Miss Tuesday and
  Wednesday is still Wednesday.
- `completion` — the clock starts when you actually did it. Water the plants
  five days after you last watered them, not five days after you meant to.

Occurrences are never backfilled. Being three days late on a daily task
produces one next occurrence, not three.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class RepeatUnit(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class RepeatFrom(StrEnum):
    SCHEDULE = "schedule"
    COMPLETION = "completion"


class RepeatDays(StrEnum):
    """Individual days of the week.

    Individual rather than groups because real schedules are not tidy — the bins
    go out on a Wednesday. Stored as a comma-separated set, which is what makes
    any combination expressible without a schema change.
    """

    MONDAY = "mon"
    TUESDAY = "tue"
    WEDNESDAY = "wed"
    THURSDAY = "thu"
    FRIDAY = "fri"
    SATURDAY = "sat"
    SUNDAY = "sun"


# Monday is 0 in date.weekday().
_WEEKDAY_NUMBERS: dict[str, int] = {
    RepeatDays.MONDAY: 0,
    RepeatDays.TUESDAY: 1,
    RepeatDays.WEDNESDAY: 2,
    RepeatDays.THURSDAY: 3,
    RepeatDays.FRIDAY: 4,
    RepeatDays.SATURDAY: 5,
    RepeatDays.SUNDAY: 6,
}

DAY_LABELS: dict[str, str] = {
    RepeatDays.MONDAY: "Monday",
    RepeatDays.TUESDAY: "Tuesday",
    RepeatDays.WEDNESDAY: "Wednesday",
    RepeatDays.THURSDAY: "Thursday",
    RepeatDays.FRIDAY: "Friday",
    RepeatDays.SATURDAY: "Saturday",
    RepeatDays.SUNDAY: "Sunday",
}

_WORKING_WEEK = frozenset({"mon", "tue", "wed", "thu", "fri"})
_WEEKEND = frozenset({"sat", "sun"})

MAX_LOOKAHEAD_DAYS = 366


class RecurrenceError(ValueError):
    pass


@dataclass(frozen=True)
class Rule:
    """A parsed repeat rule. Either an interval or a set of weekdays."""

    every: int | None = None
    unit: str | None = None
    days: frozenset[str] = frozenset()
    anchor: str = RepeatFrom.SCHEDULE

    @property
    def is_recurring(self) -> bool:
        return bool(self.days) or (self.every is not None and self.unit is not None)


def parse_days(raw: str | None) -> frozenset[str]:
    """Read a stored day set, ignoring blanks and unknown values."""
    if not raw:
        return frozenset()
    valid = {str(d) for d in RepeatDays}
    return frozenset(
        part.strip() for part in raw.split(",") if part.strip() in valid
    )


def format_days(days: frozenset[str] | set[str] | None) -> str | None:
    """Store a day set in a stable order, so the column is comparable."""
    if not days:
        return None
    ordered = [str(d) for d in RepeatDays if str(d) in days]
    return ",".join(ordered) or None


def rule_from_row(row) -> Rule:
    """Build a Rule from an item row (sqlite3.Row or mapping)."""
    def field(name):
        try:
            return row[name]
        except (KeyError, IndexError):
            return None

    return Rule(
        every=field("repeat_every"),
        unit=field("repeat_unit"),
        days=parse_days(field("repeat_days")),
        anchor=field("repeat_from") or RepeatFrom.SCHEDULE,
    )


def _add_months(start: date, months: int) -> date:
    """Add months, clamping the day to the end of the target month.

    31 January plus one month is 28 February (or the 29th) — there is no 31st,
    and rolling into March would drift the task a few days later every time.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _selected_weekdays(days: frozenset[str]) -> frozenset[int]:
    return frozenset(
        _WEEKDAY_NUMBERS[day] for day in days if day in _WEEKDAY_NUMBERS
    )


def next_occurrence(rule: Rule, *, anchor: date, today: date) -> date | None:
    """The next date this task should come back, or None if it does not repeat.

    Always strictly after `today`, so finishing late never produces a backlog
    and never produces something already overdue.
    """
    if not rule.is_recurring:
        return None

    if rule.days:
        selected = _selected_weekdays(rule.days)
        if not selected:
            return None
        # Step from the later of the anchor and today: a day-of-week rule is
        # about which day it lands on, not how far it has drifted.
        cursor = max(anchor, today)
        for _ in range(MAX_LOOKAHEAD_DAYS):
            cursor += timedelta(days=1)
            if cursor.weekday() in selected:
                return cursor
        return None

    if rule.every is None or rule.every < 1:
        raise RecurrenceError("interval must be at least 1")
    if rule.unit not in {str(u) for u in RepeatUnit}:
        raise RecurrenceError(f"unknown repeat unit: {rule.unit}")

    cursor = anchor
    # Advance until strictly in the future. One step is the normal case; the
    # loop only matters when a scheduled task was finished long after its date,
    # and it collapses the gap instead of generating every missed occurrence.
    for _ in range(MAX_LOOKAHEAD_DAYS):
        if rule.unit == RepeatUnit.DAY:
            cursor = cursor + timedelta(days=rule.every)
        elif rule.unit == RepeatUnit.WEEK:
            cursor = cursor + timedelta(weeks=rule.every)
        elif rule.unit == RepeatUnit.MONTH:
            cursor = _add_months(cursor, rule.every)
        else:
            cursor = _add_months(cursor, 12 * rule.every)
        if cursor > today:
            return cursor
    return None


def describe(rule: Rule) -> str:
    """Human phrasing for the UI, so a rule can be read back at a glance."""
    if not rule.is_recurring:
        return "does not repeat"

    if rule.days:
        # Collapse the two combinations that have a natural name, so a common
        # schedule does not read as a list of five days.
        if rule.days == frozenset(_WEEKDAY_NUMBERS):
            return "every day"
        if rule.days == _WORKING_WEEK:
            return "every weekday"
        if rule.days == _WEEKEND:
            return "every weekend"

        names = [DAY_LABELS[str(d)] for d in RepeatDays if str(d) in rule.days]
        if len(names) == 1:
            return f"every {names[0]}"
        return f"every {', '.join(names[:-1])} and {names[-1]}"

    unit = rule.unit if rule.every == 1 else f"{rule.unit}s"
    every = "every" if rule.every == 1 else f"every {rule.every}"
    suffix = " from completion" if rule.anchor == RepeatFrom.COMPLETION else ""
    return f"{every} {unit}{suffix}"

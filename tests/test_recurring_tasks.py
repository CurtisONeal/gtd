"""Recurring tasks at the store level: what happens when one is completed.

The date arithmetic is covered in test_recurrence.py. What matters here is that
completing spawns exactly one successor, that the successor is a normal Next
Action riding the existing tickler, and that nothing spawns when it shouldn't.
"""

from datetime import date, timedelta

import pytest

from gtd.models import ItemState
from gtd.recurrence import RepeatDays, RepeatFrom, RepeatUnit


@pytest.fixture
def daily(store):
    item_id = store.capture("take medication")
    store.set_state(item_id, ItemState.NEXT_ACTION)
    store.set_recurrence(item_id, every=1, unit=RepeatUnit.DAY)
    return item_id


def test_completing_a_repeating_task_spawns_the_next_one(store, daily):
    next_id = store.complete(daily)

    assert next_id is not None
    assert next_id != daily
    successor = store.get_item(next_id)
    assert successor["title"] == "take medication"
    assert successor["state"] == ItemState.NEXT_ACTION
    assert successor["defer_until"] == (date.today() + timedelta(days=1)).isoformat()


def test_the_completed_one_stays_in_done_as_history(store, daily):
    """Spawning was chosen over re-arming precisely so this record exists."""
    store.complete(daily)

    original = store.get_item(daily)
    assert original["state"] == ItemState.DONE
    assert original["completed_at"]


def test_the_successor_is_hidden_by_the_tickler_until_its_date(store, daily):
    """Recurrence rides the existing tickler rather than inventing a scheduler."""
    store.complete(daily)

    visible = store.list_items(ItemState.NEXT_ACTION)
    assert visible == []

    including_deferred = store.list_items(ItemState.NEXT_ACTION, include_deferred=True)
    assert len(including_deferred) == 1


def test_completing_only_ever_produces_one_successor(store, daily):
    """Completing twice must not mint a second copy."""
    first = store.complete(daily)
    second = store.complete(daily)

    assert second is None
    assert len(store.list_items(ItemState.NEXT_ACTION, include_deferred=True)) == 1
    assert first is not None


def test_a_non_repeating_task_spawns_nothing(store):
    item_id = store.capture("one-off thing")
    store.set_state(item_id, ItemState.NEXT_ACTION)

    assert store.complete(item_id) is None
    assert store.list_items(ItemState.NEXT_ACTION, include_deferred=True) == []


def test_metadata_carries_forward(store):
    context = store.list_contexts()[0]["id"]
    area = store.list_areas()[0]["id"]
    project = store.create_project("Health")
    item_id = store.capture("take medication")
    store.set_state(
        item_id,
        ItemState.NEXT_ACTION,
        context_id=context,
        area_id=area,
        project_id=project,
        energy="low",
        time_estimate_min=2,
        priority=1,
    )
    store.set_recurrence(item_id, every=1, unit=RepeatUnit.DAY)

    successor = store.get_item(store.complete(item_id))

    assert successor["context_id"] == context
    assert successor["area_id"] == area
    assert successor["project_id"] == project
    assert successor["energy"] == "low"
    assert successor["time_estimate_min"] == 2
    assert successor["priority"] == 1


def test_blockers_do_not_carry_forward(store, daily):
    """A prerequisite satisfied once must not be recreated for the next
    occurrence — it would put the successor straight back into Waiting For."""
    blocker = store.capture("prerequisite")
    store.add_dependency(daily, blocker)

    successor = store.get_item(store.complete(daily))

    assert store.list_dependencies(successor["id"]) == []
    assert successor["waiting_on"] is None


def test_the_successor_records_what_it_came_from(store, daily):
    successor = store.get_item(store.complete(daily))

    assert successor["recurs_from_id"] == daily


def test_a_deadline_moves_with_the_occurrence(store):
    """Otherwise a monthly bill would keep January's due date forever."""
    item_id = store.capture("pay rent")
    store.set_state(item_id, ItemState.NEXT_ACTION, due_date=date.today().isoformat())
    store.set_recurrence(item_id, every=1, unit=RepeatUnit.MONTH)

    successor = store.get_item(store.complete(item_id))

    assert successor["due_date"] == successor["defer_until"]
    assert successor["due_date"] > date.today().isoformat()


def test_a_task_without_a_deadline_does_not_gain_one(store, daily):
    successor = store.get_item(store.complete(daily))

    assert successor["due_date"] is None
    assert successor["defer_until"] is not None


def test_day_of_week_recurrence_lands_on_a_selected_day(store):
    item_id = store.capture("stand-up")
    store.set_state(item_id, ItemState.NEXT_ACTION)
    store.set_recurrence(item_id, days={RepeatDays.SATURDAY, RepeatDays.SUNDAY})

    successor = store.get_item(store.complete(item_id))

    landed = date.fromisoformat(successor["defer_until"])
    assert landed.weekday() in {5, 6}
    assert landed > date.today()


def test_setting_days_clears_an_interval_and_the_reverse(store, daily):
    """A rule must never be half interval and half day-of-week."""
    store.set_recurrence(daily, days={RepeatDays.WEDNESDAY})
    item = store.get_item(daily)
    assert item["repeat_days"] == "wed"
    assert item["repeat_every"] is None and item["repeat_unit"] is None

    store.set_recurrence(daily, every=2, unit=RepeatUnit.WEEK)
    item = store.get_item(daily)
    assert item["repeat_days"] is None
    assert item["repeat_every"] == 2


def test_clearing_recurrence_stops_it_repeating(store, daily):
    store.set_recurrence(daily)

    assert store.complete(daily) is None


def test_an_invalid_rule_is_rejected_when_set(store, daily):
    with pytest.raises(ValueError, match="at least 1"):
        store.set_recurrence(daily, every=0, unit=RepeatUnit.DAY)
    with pytest.raises(ValueError, match="unknown repeat unit"):
        store.set_recurrence(daily, every=1, unit="fortnight")


def test_completion_anchored_tasks_measure_from_today_not_the_plan(store):
    """Finish a 5-day task a month late and the next one is 5 days from now."""
    item_id = store.capture("water the plants")
    long_ago = (date.today() - timedelta(days=30)).isoformat()
    store.set_state(item_id, ItemState.NEXT_ACTION, defer_until=long_ago)
    store.set_recurrence(
        item_id, every=5, unit=RepeatUnit.DAY, anchor=RepeatFrom.COMPLETION
    )

    successor = store.get_item(store.complete(item_id))

    assert successor["defer_until"] == (date.today() + timedelta(days=5)).isoformat()


def test_schedule_anchored_tasks_never_land_in_the_past(store):
    """A schedule-anchored task finished very late must still come back in the
    future — collapsing the gap rather than generating every missed occurrence."""
    item_id = store.capture("weekly review")
    long_ago = (date.today() - timedelta(days=90)).isoformat()
    store.set_state(item_id, ItemState.NEXT_ACTION, defer_until=long_ago)
    store.set_recurrence(item_id, every=1, unit=RepeatUnit.WEEK)

    successor = store.get_item(store.complete(item_id))

    assert successor["defer_until"] > date.today().isoformat()
    assert len(store.list_items(ItemState.NEXT_ACTION, include_deferred=True)) == 1


# ── Routes ───────────────────────────────────────────────────────────────────


def _edit(client, item_id, **overrides):
    """Submit the edit form the way the browser does — every field present."""
    data = {
        "title": "take medication",
        "notes": "",
        "state": "next_action",
        "back": "/list/next_action",
        "repeat_mode": "",
        "repeat_every": "1",
        "repeat_unit": "day",
        "repeat_from": "schedule",
    }
    data.update(overrides)
    return client.post(f"/items/{item_id}/edit", data=data)


def test_setting_an_interval_rule_through_the_form(signed_in, app):
    store = app.state.store
    item_id = store.capture("take medication")

    _edit(signed_in, item_id, repeat_mode="interval", repeat_every="3", repeat_unit="week")

    item = store.get_item(item_id)
    assert item["repeat_every"] == 3
    assert item["repeat_unit"] == "week"
    assert item["repeat_days"] is None


def test_setting_day_flags_through_the_form(signed_in, app):
    """The three checkboxes post as a repeated field name."""
    store = app.state.store
    item_id = store.capture("stand-up")

    _edit(signed_in, item_id, repeat_mode="days", repeat_days=["wed", "sat"])

    item = store.get_item(item_id)
    assert item["repeat_days"] == "wed,sat"
    assert item["repeat_every"] is None


def test_turning_repetition_off_clears_it(signed_in, app):
    store = app.state.store
    item_id = store.capture("take medication")
    store.set_recurrence(item_id, every=1, unit="day")

    _edit(signed_in, item_id, repeat_mode="")

    item = store.get_item(item_id)
    assert item["repeat_every"] is None
    assert item["repeat_days"] is None
    assert store.complete(item_id) is None


def test_switching_to_days_does_not_leave_the_interval_behind(signed_in, app):
    """Stale values in the unused inputs must not resurrect the old rule."""
    store = app.state.store
    item_id = store.capture("stand-up")
    store.set_recurrence(item_id, every=3, unit="week")

    _edit(signed_in, item_id, repeat_mode="days", repeat_days=["wed"],
          repeat_every="3", repeat_unit="week")

    item = store.get_item(item_id)
    assert item["repeat_days"] == "wed"
    assert item["repeat_every"] is None, "the interval should have been cleared"


def test_an_invalid_interval_from_the_form_does_not_500(signed_in, app):
    store = app.state.store
    item_id = store.capture("take medication")

    response = _edit(signed_in, item_id, repeat_mode="interval", repeat_every="0")

    assert response.status_code in (200, 303)
    assert store.get_item(item_id)["repeat_every"] is None


def test_the_list_page_shows_that_a_task_repeats(signed_in, app):
    store = app.state.store
    item_id = store.capture("take medication")
    store.set_state(item_id, ItemState.NEXT_ACTION)
    store.set_recurrence(item_id, days={RepeatDays.WEDNESDAY})

    body = signed_in.get("/list/next_action").text

    assert "repeats every Wednesday" in body


def test_completing_from_the_list_creates_the_next_occurrence(signed_in, app):
    store = app.state.store
    item_id = store.capture("take medication")
    store.set_state(item_id, ItemState.NEXT_ACTION)
    store.set_recurrence(item_id, every=1, unit=RepeatUnit.DAY)

    signed_in.post(f"/items/{item_id}/complete", data={"back": "/list/next_action"})

    assert store.get_item(item_id)["state"] == ItemState.DONE
    upcoming = store.list_items(ItemState.NEXT_ACTION, include_deferred=True)
    assert len(upcoming) == 1
    assert upcoming[0]["id"] != item_id

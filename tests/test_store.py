from datetime import date, timedelta

import pytest

from gtd.models import ItemState, ProjectStatus, Source


# ── Capture ──────────────────────────────────────────────────────────────────

def test_capture_lands_in_inbox(store):
    item_id = store.capture("Call the dentist")
    item = store.get_item(item_id)
    assert item["title"] == "Call the dentist"
    assert item["state"] == ItemState.INBOX
    assert item["source"] == Source.WEB
    assert item["completed_at"] is None


def test_capture_strips_and_rejects_empty(store):
    assert store.get_item(store.capture("  padded  "))["title"] == "padded"
    with pytest.raises(ValueError):
        store.capture("   ")


def test_capture_many_is_a_brain_dump(store):
    ids = store.capture_many(["one", "", "  ", "two", "three"])
    assert len(ids) == 3
    assert {r["title"] for r in store.list_items(ItemState.INBOX)} == {"one", "two", "three"}


def test_capture_records_source(store):
    item = store.get_item(store.capture("from discord", source=Source.DISCORD))
    assert item["source"] == Source.DISCORD


# ── State transitions: the core of the design ────────────────────────────────

@pytest.mark.parametrize(
    "target",
    [ItemState.NEXT_ACTION, ItemState.WAITING_FOR, ItemState.SOMEDAY, ItemState.REFERENCE],
)
def test_item_moves_between_lists_with_one_update(store, target):
    item_id = store.capture("something")
    store.set_state(item_id, target)

    assert store.get_item(item_id)["state"] == target
    assert store.list_items(ItemState.INBOX) == []       # left the inbox
    assert len(store.list_items(target)) == 1            # arrived exactly once


def test_delegating_records_who_we_are_waiting_on(store):
    item_id = store.capture("Get the signed contract back")
    store.set_state(item_id, ItemState.WAITING_FOR, waiting_on="Dana")
    assert store.get_item(item_id)["waiting_on"] == "Dana"


def test_complete_then_uncomplete_round_trips(store):
    item_id = store.capture("two minute thing")
    store.set_state(item_id, ItemState.NEXT_ACTION)

    store.complete(item_id)
    done = store.get_item(item_id)
    assert done["state"] == ItemState.DONE and done["completed_at"] is not None

    # No archive row to reconcile — reversing is just another UPDATE.
    store.uncomplete(item_id)
    back = store.get_item(item_id)
    assert back["state"] == ItemState.NEXT_ACTION and back["completed_at"] is None


def test_soft_delete_keeps_the_row_recoverable(store):
    item_id = store.capture("oops")
    store.delete_item(item_id)
    assert store.get_item(item_id)["state"] == ItemState.TRASHED

    store.delete_item(item_id, hard=True)
    assert store.get_item(item_id) is None


def test_update_item_rejects_unknown_fields(store):
    item_id = store.capture("x")
    with pytest.raises(ValueError, match="unknown field"):
        store.update_item(item_id, titel="typo")


def test_blank_strings_become_null_not_empty(store):
    item_id = store.capture("x")
    store.update_item(item_id, due_date="", waiting_on="  ")
    item = store.get_item(item_id)
    assert item["due_date"] is None and item["waiting_on"] is None


# ── The tickler: deferred items disappear until their date ───────────────────

def test_future_deferred_items_are_hidden(store):
    visible = store.capture("do now")
    deferred = store.capture("not yet")
    store.set_state(visible, ItemState.NEXT_ACTION)
    store.set_state(
        deferred,
        ItemState.NEXT_ACTION,
        defer_until=(date.today() + timedelta(days=30)).isoformat(),
    )

    titles = [r["title"] for r in store.list_items(ItemState.NEXT_ACTION)]
    assert titles == ["do now"]

    all_titles = {
        r["title"] for r in store.list_items(ItemState.NEXT_ACTION, include_deferred=True)
    }
    assert all_titles == {"do now", "not yet"}


def test_deferred_item_reappears_once_its_date_arrives(store):
    item_id = store.capture("ripe")
    store.set_state(
        item_id,
        ItemState.NEXT_ACTION,
        defer_until=(date.today() - timedelta(days=1)).isoformat(),
    )
    assert len(store.list_items(ItemState.NEXT_ACTION)) == 1


# ── Ordering & filtering ─────────────────────────────────────────────────────

def test_priority_orders_before_unprioritized(store):
    low = store.capture("no priority")
    high = store.capture("urgent")
    store.set_state(low, ItemState.NEXT_ACTION)
    store.set_state(high, ItemState.NEXT_ACTION, priority=1)

    assert [r["title"] for r in store.list_items(ItemState.NEXT_ACTION)][0] == "urgent"


def test_filter_by_context(store):
    contexts = {c["name"]: c["id"] for c in store.list_contexts()}
    at_computer = store.capture("write code")
    at_errands = store.capture("buy milk")
    store.set_state(at_computer, ItemState.NEXT_ACTION, context_id=contexts["@computer"])
    store.set_state(at_errands, ItemState.NEXT_ACTION, context_id=contexts["@errands"])

    rows = store.list_items(ItemState.NEXT_ACTION, context_id=contexts["@computer"])
    assert [r["title"] for r in rows] == ["write code"]
    assert rows[0]["context_name"] == "@computer"


def test_counts_by_state_covers_every_state(store):
    store.set_state(store.capture("a"), ItemState.NEXT_ACTION)
    store.capture("b")

    counts = store.counts_by_state()
    assert counts[ItemState.INBOX] == 1
    assert counts[ItemState.NEXT_ACTION] == 1
    assert counts[ItemState.SOMEDAY] == 0          # present even when empty
    assert set(counts) == {str(s) for s in ItemState}


def test_next_inbox_item_is_fifo(store):
    first = store.capture("oldest")
    store.capture("newer")
    assert store.next_inbox_item()["id"] == first

    store.set_state(first, ItemState.NEXT_ACTION)
    assert store.next_inbox_item()["title"] == "newer"


def test_next_inbox_item_none_when_empty(store):
    assert store.next_inbox_item() is None


def test_due_soon_includes_overdue_and_excludes_far_future(store):
    overdue = store.capture("late")
    soon = store.capture("this week")
    far = store.capture("next year")
    for i, d in (
        (overdue, date.today() - timedelta(days=3)),
        (soon, date.today() + timedelta(days=2)),
        (far, date.today() + timedelta(days=300)),
    ):
        store.set_state(i, ItemState.NEXT_ACTION, due_date=d.isoformat())

    assert {r["title"] for r in store.due_soon()} == {"late", "this week"}


# ── Item dependencies: blocked work waits for prerequisite work ───────────────

def test_waiting_item_can_be_blocked_by_another_item(store):
    blocker = store.capture("Buy cookies")
    blocked = store.capture("Eat cookies")
    store.set_state(blocker, ItemState.NEXT_ACTION)
    store.set_state(blocked, ItemState.WAITING_FOR)

    store.add_dependency(blocked, blocker)

    item = store.list_items(ItemState.WAITING_FOR)[0]
    assert item["title"] == "Eat cookies"
    assert item["blocked_by_titles"] == "Buy cookies"
    assert store.list_dependencies(blocked)[0]["prerequisite_item_id"] == blocker


def test_completing_a_prerequisite_unblocks_waiting_items(store):
    blocker = store.capture("Buy cookies")
    blocked = store.capture("Eat cookies")
    store.set_state(blocker, ItemState.NEXT_ACTION)
    store.set_state(blocked, ItemState.WAITING_FOR)
    store.add_dependency(blocked, blocker)

    store.complete(blocker)

    assert store.get_item(blocked)["state"] == ItemState.NEXT_ACTION
    assert store.list_dependencies(blocked) == []


def test_dependency_rejects_self_blocking(store):
    item_id = store.capture("Impossible loop")
    with pytest.raises(ValueError, match="itself"):
        store.add_dependency(item_id, item_id)


def test_dependency_rejects_cycles(store):
    first = store.capture("First")
    second = store.capture("Second")
    store.add_dependency(second, first)

    with pytest.raises(ValueError, match="cycle"):
        store.add_dependency(first, second)


# ── Projects ─────────────────────────────────────────────────────────────────

def test_project_lifecycle_and_open_action_count(store):
    pid = store.create_project("Redo the deck", outcome="Deck usable by summer")
    action = store.capture("Price out lumber")
    store.set_state(action, ItemState.NEXT_ACTION, project_id=pid)

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["open_actions"] == 1
    assert projects[0]["outcome"] == "Deck usable by summer"

    store.complete(action)
    assert store.list_projects()[0]["open_actions"] == 0   # now stalled

    store.complete_project(pid)
    assert store.list_projects() == []                     # no longer active
    assert store.get_project(pid)["status"] == ProjectStatus.DONE


def test_project_with_waiting_item_is_not_stalled_without_next_action(store):
    pid = store.create_project("Cookie party")
    waiting = store.capture("Eat cookies")
    store.set_state(waiting, ItemState.WAITING_FOR, project_id=pid, waiting_on="Buy cookies")

    project = store.list_projects()[0]
    assert project["open_actions"] == 0
    assert project["waiting_items"] == 1


def test_project_name_required(store):
    with pytest.raises(ValueError):
        store.create_project("  ")


def test_items_can_be_filtered_to_a_project(store):
    pid = store.create_project("Website")
    mine = store.capture("write copy")
    other = store.capture("unrelated")
    store.set_state(mine, ItemState.NEXT_ACTION, project_id=pid)
    store.set_state(other, ItemState.NEXT_ACTION)

    rows = store.list_items(ItemState.NEXT_ACTION, project_id=pid)
    assert [r["title"] for r in rows] == ["write copy"]
    assert rows[0]["project_name"] == "Website"


# ── Seeded defaults & users ──────────────────────────────────────────────────

def test_defaults_are_seeded_once(store, db):
    assert len(store.list_contexts()) > 0
    assert len(store.list_areas()) > 0

    before = len(store.list_contexts())
    db.init_schema()                      # re-running startup must not duplicate
    assert len(store.list_contexts()) == before


def test_upsert_user_is_idempotent_and_case_insensitive(store):
    store.upsert_user("Curtis", "hash-one")
    store.upsert_user("curtis", "hash-two")
    assert store.user_count() == 1
    assert store.get_user("CURTIS")["password_hash"] == "hash-two"

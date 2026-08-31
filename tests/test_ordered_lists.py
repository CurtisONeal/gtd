"""Ordered lists: rank as sequence within a group.

Books, checklists and technology projects all sit on this. The behaviour worth
protecting is not "rank exists" but that ordering survives the states real data
arrives in — never ranked, ranked with gaps, at the ends of the list.
"""

import sqlite3

import pytest

from gtd.db import MIGRATIONS, SCHEMA, SCHEMA_VERSION, Database
from gtd.models import ItemState
from gtd.store import Store


def titles(store, state=ItemState.REFERENCE):
    return [row["title"] for row in store.list_ordered(state)]


def test_appending_keeps_insertion_order(store):
    for title in ["alpha", "beta", "gamma"]:
        store.append_to_ordered(title, ItemState.REFERENCE)
    assert titles(store) == ["alpha", "beta", "gamma"]


def test_moving_up_and_down_swaps_with_the_neighbour(store):
    ids = [store.append_to_ordered(t, ItemState.REFERENCE) for t in ["a", "b", "c"]]

    assert store.move_in_order(ids[2], -1) is True
    assert titles(store) == ["a", "c", "b"]

    assert store.move_in_order(ids[0], +1) is True
    assert titles(store) == ["c", "a", "b"]


def test_moving_past_either_end_reports_no_move(store):
    ids = [store.append_to_ordered(t, ItemState.REFERENCE) for t in ["a", "b"]]

    assert store.move_in_order(ids[0], -1) is False
    assert store.move_in_order(ids[1], +1) is False
    assert titles(store) == ["a", "b"]


def test_rank_is_independent_of_priority(store):
    """Rank is sequence, priority is importance. Setting one must not reorder
    the other — conflating them was the thing the design explicitly rejected."""
    ids = [store.append_to_ordered(t, ItemState.REFERENCE) for t in ["a", "b", "c"]]
    store.update_item(ids[2], priority=1)
    store.update_item(ids[0], priority=3)

    assert titles(store) == ["a", "b", "c"]


def test_unranked_items_sort_last_and_can_still_be_moved(store):
    """Items predate the ordered list they land in: captured normally, rank
    NULL. They must not vanish, and must become orderable on first move."""
    store.append_to_ordered("ranked", ItemState.REFERENCE)
    legacy = store.capture("never ranked", state=ItemState.REFERENCE)

    assert titles(store) == ["ranked", "never ranked"]

    assert store.move_in_order(legacy, -1) is True
    assert titles(store) == ["never ranked", "ranked"]


def test_ordering_survives_a_gap_left_by_a_deleted_row(store):
    """Ranks are only guaranteed ordered, not contiguous, so adjacency must be
    found by comparison rather than by rank ± 1."""
    ids = [store.append_to_ordered(t, ItemState.REFERENCE) for t in ["a", "b", "c", "d"]]
    store.delete_item(ids[1], hard=True)

    assert store.move_in_order(ids[2], -1) is True
    assert titles(store) == ["c", "a", "d"]


def test_each_state_orders_independently(store):
    store.append_to_ordered("ref one", ItemState.REFERENCE)
    someday = store.append_to_ordered("someday one", ItemState.SOMEDAY)

    assert store.move_in_order(someday, -1) is False
    assert titles(store, ItemState.SOMEDAY) == ["someday one"]
    assert titles(store) == ["ref one"]


def test_unknown_grouping_column_is_rejected_before_any_sql(store):
    """`group` is interpolated into SQL as a column name, so the whitelist is
    the only thing standing between a caller and arbitrary SQL."""
    item_id = store.append_to_ordered("a", ItemState.REFERENCE)

    with pytest.raises(ValueError, match="not a rank grouping column"):
        store.move_in_order(item_id, -1, group="title; DROP TABLE items")
    with pytest.raises(ValueError, match="not a rank grouping column"):
        store.append_to_ordered("b", ItemState.REFERENCE, group="nope")

    assert titles(store) == ["a"]


def test_invalid_delta_is_rejected(store):
    item_id = store.append_to_ordered("a", ItemState.REFERENCE)
    with pytest.raises(ValueError, match="delta must be"):
        store.move_in_order(item_id, 2)


def _columns_added_after(version: int) -> set[str]:
    """Column names that migrations later than `version` introduce."""
    return {
        statement.split("ADD COLUMN")[1].split()[0]
        for later, statements in MIGRATIONS.items()
        if later > version
        for statement in statements
        if "ADD COLUMN" in statement
    }


def _schema_at(version: int) -> str:
    """Today's schema with every later-added column removed.

    Derived from MIGRATIONS rather than hardcoded, so adding a migration keeps
    these tests honest instead of quietly making them test nothing.
    """
    added = _columns_added_after(version)
    kept = []
    for line in SCHEMA.splitlines():
        # The column definition itself.
        if line.strip().split(" ")[0] in added:
            continue
        kept.append(line)
    return "\n".join(kept)


@pytest.mark.parametrize("from_version", sorted(MIGRATIONS))
def test_migrating_from_each_previous_version_reaches_existing_data(tmp_path, from_version):
    """A schema bump that only moves the version number is a silent no-op:
    CREATE TABLE IF NOT EXISTS will not add a column to a table that exists.

    Encodes that every upgrade path actually alters a real database that was
    built at the older version, with rows already in it.
    """
    start = from_version - 1
    path = tmp_path / f"v{start}.db"
    expected = _columns_added_after(start)
    assert expected, "nothing to migrate — the fixture would prove nothing"

    conn = sqlite3.connect(path)
    conn.executescript(_schema_at(start))
    conn.execute("INSERT INTO schema_version (version) VALUES (?)", (start,))
    conn.execute(
        "INSERT INTO items (title, created_at, updated_at) VALUES (?, ?, ?)",
        ("pre-existing", "2026-01-01", "2026-01-01"),
    )
    conn.commit()

    # Check the built table, not the schema text: column names also appear in
    # comments, and it is the actual absence that makes the fixture meaningful.
    before = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    assert not (expected & before), f"fixture already has {expected & before}"
    conn.close()

    Database(path).init_schema(seed_defaults=False)

    conn = sqlite3.connect(path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(items)")}
    assert expected <= columns
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1

    # Idempotent: startup runs this on every boot.
    Database(path).init_schema(seed_defaults=False)
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION


def test_ordered_list_ignores_items_in_other_states(store):
    store.append_to_ordered("kept", ItemState.REFERENCE)
    gone = store.append_to_ordered("moved away", ItemState.REFERENCE)
    store.set_state(gone, ItemState.SOMEDAY)

    assert titles(store) == ["kept"]

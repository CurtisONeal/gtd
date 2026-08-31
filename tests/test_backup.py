"""Backup and restore.

The property that matters is not "a file appeared" but that the file is a
sound, complete database — and that a bad one is refused rather than restored.
"""

import sqlite3

import pytest

from gtd import backup
from gtd.db import Database
from gtd.models import ItemState
from gtd.store import Store


@pytest.fixture
def populated(tmp_path):
    """A real database with rows in several states."""
    path = tmp_path / "live.db"
    db = Database(path)
    db.init_schema()
    store = Store(db)
    store.capture("inbox thing")
    store.set_state(store.capture("an action"), ItemState.NEXT_ACTION)
    store.capture_many(["one", "two", "three"])
    return path, store


def test_a_snapshot_captures_every_row(populated, tmp_path):
    path, store = populated
    expected = sum(store.counts_by_state().values())

    snapshot = backup.create_snapshot(path, tmp_path / "backups")

    assert snapshot.items == expected
    assert snapshot.path.exists()
    assert snapshot.size_bytes > 0


def test_a_snapshot_is_consistent_while_the_database_has_uncommitted_wal(populated, tmp_path):
    """The reason VACUUM INTO is used instead of copying the file: in WAL mode
    committed pages can still be sitting in the -wal sidecar, and a file-level
    copy of just the .db can miss them.
    """
    path, store = populated
    # Write through a separate connection and leave the WAL un-checkpointed.
    extra = sqlite3.connect(path)
    extra.execute("PRAGMA journal_mode=WAL")
    extra.execute(
        "INSERT INTO items (title, created_at, updated_at) VALUES ('in the wal','x','x')"
    )
    extra.commit()

    snapshot = backup.create_snapshot(path, tmp_path / "backups")

    conn = sqlite3.connect(snapshot.path)
    titles = [r[0] for r in conn.execute("SELECT title FROM items")]
    extra.close()
    assert "in the wal" in titles, "snapshot missed a committed row still in the WAL"


def test_snapshots_are_listed_newest_first(populated, tmp_path):
    path, _ = populated
    backup_dir = tmp_path / "backups"
    first = backup.create_snapshot(path, backup_dir)
    # Names carry a UTC timestamp; force a distinct one rather than sleeping.
    second = first.path.with_name("gtd-29990101T000000Z.db")
    first.path.replace(second)
    third = backup.create_snapshot(path, backup_dir)

    listed = backup.list_snapshots(backup_dir)

    assert listed[0] == second
    assert third.path in listed


def test_pruning_keeps_the_newest(populated, tmp_path):
    path, _ = populated
    backup_dir = tmp_path / "backups"
    made = []
    for stamp in ["20260101T000000Z", "20260102T000000Z", "20260103T000000Z"]:
        snap = backup.create_snapshot(path, backup_dir)
        renamed = snap.path.with_name(f"gtd-{stamp}.db")
        snap.path.replace(renamed)
        made.append(renamed)

    removed = backup.prune(backup_dir, keep=2)

    remaining = backup.list_snapshots(backup_dir)
    assert len(remaining) == 2
    assert made[0] in removed
    assert made[2] in remaining


def test_pruning_refuses_to_keep_nothing(tmp_path):
    with pytest.raises(backup.BackupError, match="at least 1"):
        backup.prune(tmp_path, keep=0)


def test_a_corrupt_snapshot_is_refused(tmp_path):
    bogus = tmp_path / "gtd-20260101T000000Z.db"
    bogus.write_bytes(b"this is not a database")

    with pytest.raises(backup.BackupError):
        backup.inspect(bogus)


def test_a_valid_database_that_is_not_gtd_is_refused(tmp_path):
    """Guards the restore path: a sound SQLite file is not necessarily ours,
    and restoring one would destroy the real database."""
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE unrelated (id INTEGER)")
    conn.commit()
    conn.close()

    with pytest.raises(backup.BackupError, match="not a GTD database"):
        backup.inspect(other)


def test_restore_replaces_the_database(populated, tmp_path):
    path, store = populated
    snapshot = backup.create_snapshot(path, tmp_path / "backups")
    before = snapshot.items

    # Lose data after the snapshot was taken.
    store.capture("added after the backup")
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM items")
    conn.commit()
    conn.close()
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0

    restored = backup.restore(snapshot.path, path)

    assert restored.items == before


def test_restore_keeps_the_database_it_replaced(populated, tmp_path):
    path, _ = populated
    snapshot = backup.create_snapshot(path, tmp_path / "backups")

    backup.restore(snapshot.path, path)

    aside = list(path.parent.glob(f"{path.name}.replaced-*"))
    assert aside, "the replaced database should be kept, not deleted"
    assert backup.inspect(aside[0]).items == snapshot.items


def test_restore_refuses_a_bad_snapshot_without_touching_the_database(populated, tmp_path):
    path, _ = populated
    before = backup.inspect(path).items
    bogus = tmp_path / "bad.db"
    bogus.write_bytes(b"not a database")

    with pytest.raises(backup.BackupError):
        backup.restore(bogus, path)

    assert backup.inspect(path).items == before, "the live database was modified"


def test_restore_clears_stale_wal_sidecars(populated, tmp_path):
    """A -wal left from the replaced database could be reapplied over the new
    file, silently reintroducing what the restore was meant to undo."""
    path, _ = populated
    snapshot = backup.create_snapshot(path, tmp_path / "backups")
    wal = path.with_name(path.name + "-wal")
    wal.write_bytes(b"stale")

    backup.restore(snapshot.path, path)

    assert not wal.exists()


def test_snapshot_of_a_missing_database_fails_clearly(tmp_path):
    with pytest.raises(backup.BackupError, match="no database at"):
        backup.create_snapshot(tmp_path / "nope.db", tmp_path / "backups")


def test_push_reports_failure_rather_than_pretending(tmp_path, populated):
    """A backup that silently stopped going offsite is the dangerous case."""
    path, _ = populated
    snapshot = backup.create_snapshot(path, tmp_path / "backups")

    with pytest.raises(backup.BackupError, match="failed"):
        backup.push(snapshot.path, "nonexistent-host-xyz:/tmp/nope", identity=None)

"""Snapshots and restores.

The database is the point, and until this existed there was no copy of it
anywhere. Two things drive the design:

**A snapshot is not `cp gtd.db`.** The database runs in WAL mode, so committed
pages can be sitting in the `-wal` file at any moment. A file-level copy — including
Time Machine — can catch a torn state. `VACUUM INTO` asks SQLite itself for a
consistent single-file copy while the app keeps running.

**A backup nobody has restored is a hypothesis.** Every snapshot is opened and
integrity-checked immediately after it is written, and `restore` refuses a file
that does not pass. `gtd backup --verify-restore` goes further and rehearses the
whole round trip into a scratch directory.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_PREFIX = "gtd-"
SNAPSHOT_SUFFIX = ".db"

# Tables whose absence means the file is not a GTD database, whatever its
# extension says. Checked before a restore overwrites anything.
REQUIRED_TABLES = frozenset({"items", "projects", "schema_version", "users"})


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    path: Path
    items: int
    schema_version: int

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def inspect(path: Path) -> Snapshot:
    """Open a database file and confirm it is a sound GTD one.

    Raises rather than returning a verdict — every caller here treats a bad
    snapshot as fatal, and a boolean would invite ignoring it.
    """
    if not path.exists():
        raise BackupError(f"no such file: {path}")

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise BackupError(f"integrity check failed for {path}: {result}")

        present = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = REQUIRED_TABLES - present
        if missing:
            raise BackupError(
                f"{path} is not a GTD database — missing {', '.join(sorted(missing))}"
            )

        items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        version = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"{path} is not readable as a database: {exc}") from exc
    finally:
        conn.close()

    return Snapshot(path=path, items=items, schema_version=version)


def create_snapshot(db_path: Path, backup_dir: Path) -> Snapshot:
    """Write one consistent snapshot and verify it before returning."""
    if not db_path.exists():
        raise BackupError(f"no database at {db_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{SNAPSHOT_PREFIX}{_timestamp()}{SNAPSHOT_SUFFIX}"
    if target.exists():
        raise BackupError(f"snapshot already exists: {target}")

    # VACUUM INTO rather than a file copy: it is SQLite's own consistent-copy
    # path and is safe while the server is running and writing.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.execute("VACUUM INTO ?", (str(target),))
    except sqlite3.DatabaseError as exc:
        target.unlink(missing_ok=True)
        raise BackupError(f"could not snapshot {db_path}: {exc}") from exc
    finally:
        conn.close()

    try:
        return inspect(target)
    except BackupError:
        # A snapshot that fails its own check is worse than none, because it
        # looks like protection. Do not leave it on disk.
        target.unlink(missing_ok=True)
        raise


def list_snapshots(backup_dir: Path) -> list[Path]:
    """Newest first. Sorted by name, which is safe because the timestamp is
    fixed-width UTC — no reliance on filesystem mtimes."""
    if not backup_dir.exists():
        return []
    return sorted(
        backup_dir.glob(f"{SNAPSHOT_PREFIX}*{SNAPSHOT_SUFFIX}"), reverse=True
    )


def prune(backup_dir: Path, keep: int) -> list[Path]:
    """Delete all but the newest `keep` snapshots. Returns what was removed."""
    if keep < 1:
        raise BackupError("keep must be at least 1")
    removed = []
    for path in list_snapshots(backup_dir)[keep:]:
        path.unlink()
        removed.append(path)
    return removed


def push(snapshot: Path, remote: str, *, identity: Path | None = None) -> None:
    """Copy a snapshot to `user@host:/path` over SSH.

    Deliberately shells out to scp rather than taking an SSH dependency: the
    transport is already there, and the credentials stay in the user's own SSH
    config rather than in this app.
    """
    command = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
    if identity:
        command += ["-i", str(identity)]
    command += [str(snapshot), remote]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise BackupError(
            f"copy to {remote} failed: {result.stderr.strip() or result.returncode}"
        )


def restore(snapshot: Path, db_path: Path, *, keep_previous: bool = True) -> Snapshot:
    """Replace the live database with a snapshot.

    The snapshot is verified *before* anything is overwritten, and the database
    being replaced is moved aside rather than deleted — restoring the wrong file
    should not be the end of the story.
    """
    inspect(snapshot)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists() and keep_previous:
        aside = db_path.with_name(f"{db_path.name}.replaced-{_timestamp()}")
        shutil.copy2(db_path, aside)

    shutil.copy2(snapshot, db_path)

    # WAL and shared-memory sidecars belong to the database that was just
    # replaced. Leaving them would let SQLite reapply a log over the new file.
    for sidecar in (
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
    ):
        sidecar.unlink(missing_ok=True)

    # Re-check what actually landed, not what we believed we copied.
    return inspect(db_path)

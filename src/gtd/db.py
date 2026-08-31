"""SQLite connection handling and schema.

Plain `sqlite3` on purpose — no ORM. The data model is small and the queries are
simple; an ORM would add a dependency and a layer of indirection for no gain.
All SQL is confined to `store.py`, so a future move to Postgres touches the
connection layer here and the queries there, and nothing else.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 5

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS areas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    emoji      TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contexts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    outcome      TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'active',
    area_id      INTEGER REFERENCES areas(id) ON DELETE SET NULL,
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    review_date  TEXT,
    completed_at TEXT
);

-- A checklist is a container, like a project — `evergreen` and a one-off's
-- completion belong to the list as a whole, not to any of its items. Its
-- membership still lives in `items`, so ADR-001 holds.
CREATE TABLE IF NOT EXISTS checklists (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    -- Evergreen lists are run repeatedly and reset; one-offs complete once.
    evergreen    INTEGER NOT NULL DEFAULT 1,
    status       TEXT NOT NULL DEFAULT 'active',
    notes        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    completed_at TEXT
);

-- The core table. Every GTD list is a `state` of this one table, so moving an
-- item between lists is a single UPDATE, never a copy plus delete.
CREATE TABLE IF NOT EXISTS items (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    notes             TEXT NOT NULL DEFAULT '',
    state             TEXT NOT NULL DEFAULT 'inbox',
    project_id        INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    context_id        INTEGER REFERENCES contexts(id) ON DELETE SET NULL,
    area_id           INTEGER REFERENCES areas(id)    ON DELETE SET NULL,
    energy            TEXT,
    time_estimate_min INTEGER,
    priority          INTEGER,
    due_date          TEXT,   -- ISO date. Hard deadline.
    defer_until       TEXT,   -- ISO date. Tickler: hidden from next actions until then.
    waiting_on        TEXT,   -- who, when state = waiting_for
    rank              INTEGER,-- sequence within an ordered list; NOT priority
    source            TEXT NOT NULL DEFAULT 'web',
    -- Books. Null on everything else; only meaningful when state = 'book'.
    book_category     TEXT,   -- a reading taxonomy, not an area of focus
    started           INTEGER NOT NULL DEFAULT 0,
    started_on        TEXT,   -- rough ISO date, only meaningful when started
    percent_complete  INTEGER,-- one of PERCENT_BUCKETS
    is_audio          INTEGER NOT NULL DEFAULT 0,
    -- Checklists. `ticked` is checklist-local and is NOT the done state: reset
    -- clears it, and a ticked item must never leave for the Done list.
    checklist_id      INTEGER REFERENCES checklists(id) ON DELETE CASCADE,
    ticked            INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    completed_at      TEXT
);

CREATE TABLE IF NOT EXISTS item_dependencies (
    blocked_item_id      INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    prerequisite_item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    created_at           TEXT NOT NULL,
    PRIMARY KEY (blocked_item_id, prerequisite_item_id),
    CHECK (blocked_item_id != prerequisite_item_id)
);

"""

# Indexes are applied *after* migrations, never with the tables. An index over a
# column that a migration is about to add would otherwise fail on every existing
# database: CREATE TABLE IF NOT EXISTS is a no-op there, so the column does not
# exist yet when the index runs.
SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_items_state       ON items(state);
CREATE INDEX IF NOT EXISTS idx_items_project     ON items(project_id);
CREATE INDEX IF NOT EXISTS idx_items_due_date    ON items(due_date);
CREATE INDEX IF NOT EXISTS idx_items_defer_until ON items(defer_until);
CREATE INDEX IF NOT EXISTS idx_projects_status   ON projects(status);
CREATE INDEX IF NOT EXISTS idx_items_checklist   ON items(checklist_id);
CREATE INDEX IF NOT EXISTS idx_checklists_status ON checklists(status);
CREATE INDEX IF NOT EXISTS idx_item_dependencies_prerequisite
    ON item_dependencies(prerequisite_item_id);
"""

# Statements that bring an *existing* database up to each version. A fresh
# database gets everything from SCHEMA above and records SCHEMA_VERSION without
# running any of these, so each entry only has to handle the upgrade path.
#
# `CREATE TABLE IF NOT EXISTS` is a no-op on a database that already has the
# table, so a new column added to SCHEMA reaches existing installs *only* if it
# also appears here. Before this existed, `init_schema` moved the version number
# without running anything, so a v2 database would have reported itself as v3
# while still missing the column.
MIGRATIONS: dict[int, tuple[str, ...]] = {
    3: ("ALTER TABLE items ADD COLUMN rank INTEGER",),
    4: (
        "ALTER TABLE items ADD COLUMN book_category TEXT",
        "ALTER TABLE items ADD COLUMN started INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE items ADD COLUMN started_on TEXT",
        "ALTER TABLE items ADD COLUMN percent_complete INTEGER",
        "ALTER TABLE items ADD COLUMN is_audio INTEGER NOT NULL DEFAULT 0",
    ),
    5: (
        # The table itself is created by SCHEMA above on every startup, so only
        # the new items columns need an ALTER here.
        "ALTER TABLE items ADD COLUMN checklist_id INTEGER REFERENCES checklists(id)",
        "ALTER TABLE items ADD COLUMN ticked INTEGER NOT NULL DEFAULT 0",
    ),
}


# Sensible starting points so a fresh install isn't an empty void. All editable.
DEFAULT_CONTEXTS = ["@computer", "@phone", "@errands", "@home", "@office", "@anywhere"]
DEFAULT_AREAS = [
    ("Personal", "🏠"),
    ("Work", "💼"),
    ("Health", "💪"),
    ("Learning", "📚"),
    ("Family", "👥"),
    ("Creative", "🎨"),
]


class Database:
    """Owns the connection to one SQLite file.

    Instantiated with an explicit path rather than reading a module-level global,
    so tests can point at a temp file without monkeypatching.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self, seed_defaults: bool = True) -> None:
        """Create tables if absent. Idempotent — safe to call on every startup."""
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            row = conn.execute("SELECT version FROM schema_version").fetchone()
            if row is None:
                # Fresh database: SCHEMA is already current, nothing to migrate.
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
                )
            elif row["version"] < SCHEMA_VERSION:
                for version in range(row["version"] + 1, SCHEMA_VERSION + 1):
                    for statement in MIGRATIONS.get(version, ()):
                        conn.execute(statement)
                conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))

            # Only now that every column exists.
            conn.executescript(SCHEMA_INDEXES)
        if seed_defaults:
            self._seed_defaults()

    def _seed_defaults(self) -> None:
        """Populate starter contexts/areas, but only into a genuinely empty table
        — never re-add something the user deliberately deleted."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.connect() as conn:
            if conn.execute("SELECT COUNT(*) AS n FROM contexts").fetchone()["n"] == 0:
                conn.executemany(
                    "INSERT INTO contexts (name, sort_order, created_at) VALUES (?, ?, ?)",
                    [(name, i, now) for i, name in enumerate(DEFAULT_CONTEXTS)],
                )
            if conn.execute("SELECT COUNT(*) AS n FROM areas").fetchone()["n"] == 0:
                conn.executemany(
                    "INSERT INTO areas (name, emoji, sort_order, created_at) VALUES (?, ?, ?, ?)",
                    [(name, emoji, i, now) for i, (name, emoji) in enumerate(DEFAULT_AREAS)],
                )

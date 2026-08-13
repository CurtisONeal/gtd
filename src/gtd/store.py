"""Repository layer. All SQL lives here.

Keeping every query in one module is what makes the "swap SQLite for Postgres
later" story real rather than aspirational — the web layer never sees SQL.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Sequence

from .db import Database
from .models import ItemState, ProjectStatus, Source


def _now() -> str:
    # Microsecond precision, not seconds: two items captured in the same second
    # must still order deterministically (a brain dump creates many at once).
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _today() -> str:
    return date.today().isoformat()


def _clean(value: Any) -> Any:
    """Normalize empty form strings to NULL so optional columns stay genuinely
    empty rather than storing ''."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


class Store:
    def __init__(self, db: Database):
        self.db = db

    # ── Items ────────────────────────────────────────────────────────────────

    def capture(
        self,
        title: str,
        *,
        notes: str = "",
        source: str = Source.WEB,
        state: str = ItemState.INBOX,
    ) -> int:
        """The front door. Deliberately takes almost nothing but a title —
        capture must never be slowed down by asking for metadata. Clarify is a
        separate step, later, on purpose."""
        title = title.strip()
        if not title:
            raise ValueError("title cannot be empty")
        now = _now()
        with self.db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO items (title, notes, state, source, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (title, notes.strip(), str(state), str(source), now, now),
            )
            return cur.lastrowid

    def capture_many(self, titles: Sequence[str], *, source: str = Source.WEB) -> list[int]:
        """Brain dump: one line per item. Blank lines ignored."""
        return [self.capture(t, source=source) for t in titles if t.strip()]

    def get_item(self, item_id: int) -> sqlite3.Row | None:
        with self.db.connect() as conn:
            return conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()

    def update_item(self, item_id: int, **fields: Any) -> None:
        """Update whitelisted columns. Unknown keys raise rather than silently
        no-op, so a typo in a form field name fails loudly."""
        allowed = {
            "title", "notes", "state", "project_id", "context_id", "area_id",
            "energy", "time_estimate_min", "priority", "due_date", "defer_until",
            "waiting_on", "source",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown field(s): {', '.join(sorted(unknown))}")
        if not fields:
            return

        # NOT NULL columns keep a string even when blank; everything else gets
        # NULL rather than '' so "unset" is genuinely unset.
        not_null = {"title", "notes", "state", "source"}

        if "title" in fields and not str(fields["title"]).strip():
            raise ValueError("title cannot be empty")

        sets = ", ".join(f"{k} = ?" for k in fields)
        values = [
            (str(v).strip() if k in not_null else _clean(v)) for k, v in fields.items()
        ]
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE items SET {sets}, updated_at = ? WHERE id = ?",
                (*values, _now(), item_id),
            )

    def set_state(self, item_id: int, state: str, **fields: Any) -> None:
        """Move an item between lists. This is the whole 'move' operation —
        one UPDATE, no cross-table bookkeeping."""
        self.update_item(item_id, state=str(state), **fields)

    def complete(self, item_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE items SET state = ?, completed_at = ?, updated_at = ? WHERE id = ?",
                (str(ItemState.DONE), _now(), _now(), item_id),
            )

    def uncomplete(self, item_id: int, *, state: str = ItemState.NEXT_ACTION) -> None:
        """Reversing completion is a single UPDATE — no archive row to hunt down."""
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE items SET state = ?, completed_at = NULL, updated_at = ? WHERE id = ?",
                (str(state), _now(), item_id),
            )

    def delete_item(self, item_id: int, *, hard: bool = False) -> None:
        with self.db.connect() as conn:
            if hard:
                conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
            else:
                conn.execute(
                    "UPDATE items SET state = ?, updated_at = ? WHERE id = ?",
                    (str(ItemState.TRASHED), _now(), item_id),
                )

    def list_items(
        self,
        state: str,
        *,
        include_deferred: bool = False,
        project_id: int | None = None,
        context_id: int | None = None,
        area_id: int | None = None,
    ) -> list[sqlite3.Row]:
        """Items in one state, newest-relevant-first.

        `include_deferred=False` hides anything with a future `defer_until` —
        that is the tickler working: deferred items genuinely disappear from
        next actions until their date arrives, instead of cluttering the list.
        """
        sql = [
            """SELECT i.*, p.name AS project_name, c.name AS context_name,
                      a.name AS area_name, a.emoji AS area_emoji
               FROM items i
               LEFT JOIN projects p ON p.id = i.project_id
               LEFT JOIN contexts c ON c.id = i.context_id
               LEFT JOIN areas    a ON a.id = i.area_id
               WHERE i.state = ?"""
        ]
        params: list[Any] = [str(state)]

        if not include_deferred:
            sql.append("AND (i.defer_until IS NULL OR i.defer_until <= ?)")
            params.append(_today())
        if project_id is not None:
            sql.append("AND i.project_id = ?")
            params.append(project_id)
        if context_id is not None:
            sql.append("AND i.context_id = ?")
            params.append(context_id)
        if area_id is not None:
            sql.append("AND i.area_id = ?")
            params.append(area_id)

        # Priority first (nulls last), then soonest due date, then oldest.
        sql.append(
            """ORDER BY
                 CASE WHEN i.priority IS NULL THEN 1 ELSE 0 END, i.priority ASC,
                 CASE WHEN i.due_date IS NULL THEN 1 ELSE 0 END, i.due_date ASC,
                 i.created_at ASC"""
        )
        with self.db.connect() as conn:
            return conn.execute(" ".join(sql), params).fetchall()

    def next_inbox_item(self) -> sqlite3.Row | None:
        """Oldest unclarified item — clarify works FIFO so nothing rots at the
        bottom of the inbox. `id` breaks any remaining tie deterministically."""
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM items WHERE state = ? ORDER BY created_at ASC, id ASC LIMIT 1",
                (str(ItemState.INBOX),),
            ).fetchone()

    def send_to_back_of_inbox(self, item_id: int) -> None:
        """'Skip for now': re-stamp created_at so FIFO puts it last. Deliberately
        not a separate column — the queue position *is* capture order."""
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE items SET created_at = ?, updated_at = ? WHERE id = ?",
                (_now(), _now(), item_id),
            )

    def counts_by_state(self) -> dict[str, int]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT state, COUNT(*) AS n FROM items GROUP BY state"
            ).fetchall()
        counts = {str(s): 0 for s in ItemState}
        for row in rows:
            counts[row["state"]] = row["n"]
        return counts

    def due_soon(self, within_days: int = 7) -> list[sqlite3.Row]:
        """Actionable items with a deadline inside the window (or overdue)."""
        from datetime import timedelta

        horizon = (date.today() + timedelta(days=within_days)).isoformat()
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT * FROM items
                   WHERE state IN (?, ?) AND due_date IS NOT NULL AND due_date <= ?
                   ORDER BY due_date ASC""",
                (str(ItemState.NEXT_ACTION), str(ItemState.WAITING_FOR), horizon),
            ).fetchall()

    # ── Projects ─────────────────────────────────────────────────────────────

    def create_project(
        self, name: str, *, outcome: str = "", area_id: int | None = None, notes: str = ""
    ) -> int:
        name = name.strip()
        if not name:
            raise ValueError("project name cannot be empty")
        now = _now()
        with self.db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO projects (name, outcome, status, area_id, notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, outcome.strip(), str(ProjectStatus.ACTIVE), area_id, notes.strip(), now, now),
            )
            return cur.lastrowid

    def get_project(self, project_id: int) -> sqlite3.Row | None:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()

    def list_projects(self, status: str | None = ProjectStatus.ACTIVE) -> list[sqlite3.Row]:
        """Projects with a live count of their open next actions — a project with
        zero is 'stalled', which is exactly what a weekly review looks for."""
        sql = """SELECT p.*, a.name AS area_name, a.emoji AS area_emoji,
                        (SELECT COUNT(*) FROM items i
                          WHERE i.project_id = p.id AND i.state = 'next_action')
                          AS open_actions
                 FROM projects p
                 LEFT JOIN areas a ON a.id = p.area_id"""
        params: list[Any] = []
        if status is not None:
            sql += " WHERE p.status = ?"
            params.append(str(status))
        sql += " ORDER BY a.sort_order, p.name"
        with self.db.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def update_project(self, project_id: int, **fields: Any) -> None:
        allowed = {"name", "outcome", "status", "area_id", "notes", "review_date"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown field(s): {', '.join(sorted(unknown))}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        values = [_clean(v) for v in fields.values()]
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE projects SET {sets}, updated_at = ? WHERE id = ?",
                (*values, _now(), project_id),
            )

    def complete_project(self, project_id: int) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE projects SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
                (str(ProjectStatus.DONE), _now(), _now(), project_id),
            )

    # ── Contexts & areas ─────────────────────────────────────────────────────

    def list_contexts(self) -> list[sqlite3.Row]:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM contexts ORDER BY sort_order, name"
            ).fetchall()

    def list_areas(self) -> list[sqlite3.Row]:
        with self.db.connect() as conn:
            return conn.execute("SELECT * FROM areas ORDER BY sort_order, name").fetchall()

    def create_context(self, name: str) -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO contexts (name, created_at) VALUES (?, ?)",
                (name.strip(), _now()),
            )
            return cur.lastrowid

    def create_area(self, name: str, emoji: str = "") -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO areas (name, emoji, created_at) VALUES (?, ?, ?)",
                (name.strip(), emoji.strip(), _now()),
            )
            return cur.lastrowid

    # ── Users ────────────────────────────────────────────────────────────────

    def get_user(self, username: str) -> sqlite3.Row | None:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM users WHERE username = ?", (username.strip().lower(),)
            ).fetchone()

    def upsert_user(self, username: str, password_hash: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)
                   ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash""",
                (username.strip().lower(), password_hash, _now()),
            )

    def user_count(self) -> int:
        with self.db.connect() as conn:
            return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]

"""Repository layer. All SQL lives here.

Keeping every query in one module is what makes the "swap SQLite for Postgres
later" story real rather than aspirational — the web layer never sees SQL.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Sequence

from .db import Database
from . import recurrence
from .models import ChecklistStatus, ItemState, ProjectStatus, Source


def _now() -> str:
    # Microsecond precision, not seconds: two items captured in the same second
    # must still order deterministically (a brain dump creates many at once).
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _today() -> str:
    return date.today().isoformat()


# Columns an ordered list may be grouped by. Whitelisted because the name is
# interpolated into SQL as a column name, which parameter binding cannot do.
RANK_GROUPS: frozenset[str] = frozenset({"book_category", "checklist_id"})


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
            "waiting_on", "rank", "source",
            "book_category", "started", "started_on", "percent_complete", "is_audio",
            "checklist_id", "ticked",
            "repeat_every", "repeat_unit", "repeat_days", "repeat_from",
            "recurs_from_id",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown field(s): {', '.join(sorted(unknown))}")
        if not fields:
            return

        # NOT NULL columns keep a string even when blank; everything else gets
        # NULL rather than '' so "unset" is genuinely unset.
        not_null = {"title", "notes", "state", "source"}

        # NOT NULL integer flags. Without this `_clean` would turn a blank form
        # value into NULL and violate the constraint — the same shape of bug as
        # the empty-string-into-a-NOT-NULL-text-column one above. An unchecked
        # checkbox sends nothing at all, and "absent" must mean false, not null.
        boolean = {"started", "is_audio", "ticked"}

        if "title" in fields and not str(fields["title"]).strip():
            raise ValueError("title cannot be empty")

        sets = ", ".join(f"{k} = ?" for k in fields)
        values = []
        for k, v in fields.items():
            if k in not_null:
                values.append(str(v).strip())
            elif k in boolean:
                values.append(1 if _clean(v) else 0)
            else:
                values.append(_clean(v))
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE items SET {sets}, updated_at = ? WHERE id = ?",
                (*values, _now(), item_id),
            )

    def set_state(self, item_id: int, state: str, **fields: Any) -> None:
        """Move an item between lists. This is the whole 'move' operation —
        one UPDATE, no cross-table bookkeeping."""
        self.update_item(item_id, state=str(state), **fields)

    def complete(self, item_id: int) -> int | None:
        """Mark done, unblock dependents, and spawn the next occurrence.

        Returns the id of the occurrence created, if the item repeats.
        """
        next_id = self._spawn_next_occurrence(item_id)
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE items SET state = ?, completed_at = ?, updated_at = ? WHERE id = ?",
                (str(ItemState.DONE), now, now, item_id),
            )
            conn.execute("DELETE FROM item_dependencies WHERE blocked_item_id = ?", (item_id,))

            dependents = conn.execute(
                """SELECT DISTINCT d.blocked_item_id
                   FROM item_dependencies d
                   JOIN items i ON i.id = d.blocked_item_id
                   WHERE d.prerequisite_item_id = ? AND i.state = ?""",
                (item_id, str(ItemState.WAITING_FOR)),
            ).fetchall()

            for row in dependents:
                blocked_id = row["blocked_item_id"]
                open_blockers = conn.execute(
                    """SELECT COUNT(*) AS n
                       FROM item_dependencies d
                       JOIN items p ON p.id = d.prerequisite_item_id
                       WHERE d.blocked_item_id = ? AND p.state != ?""",
                    (blocked_id, str(ItemState.DONE)),
                ).fetchone()["n"]
                if open_blockers == 0:
                    conn.execute(
                        """UPDATE items
                           SET state = ?, waiting_on = NULL, updated_at = ?
                           WHERE id = ? AND state = ?""",
                        (
                            str(ItemState.NEXT_ACTION),
                            now,
                            blocked_id,
                            str(ItemState.WAITING_FOR),
                        ),
                    )
                    conn.execute(
                        "DELETE FROM item_dependencies WHERE blocked_item_id = ?",
                        (blocked_id,),
                    )
        return next_id

    # ── Recurrence ───────────────────────────────────────────────────────────
    #
    # A repeating task spawns its next occurrence when it is completed. The
    # completed one stays in Done, so "did I actually do this?" has an answer —
    # which is the whole point of a recurring reminder.
    #
    # This rides on the tickler rather than inventing a scheduler: the new
    # occurrence is an ordinary Next Action with `defer_until` set, so it is
    # hidden until its date by machinery that already exists, and the list
    # already discloses how many it is withholding.

    # Copied to the next occurrence. Deliberately excludes dependencies,
    # `waiting_on` and any book/checklist columns: a repeating task is a next
    # action, and carrying blockers forward would recreate a wait that was
    # already satisfied.
    _RECURRING_FIELDS = (
        "title", "notes", "project_id", "context_id", "area_id", "energy",
        "time_estimate_min", "priority", "source",
        "repeat_every", "repeat_unit", "repeat_days", "repeat_from",
    )

    def _spawn_next_occurrence(self, item_id: int) -> int | None:
        """Create the next occurrence of a repeating item, if it repeats."""
        item = self.get_item(item_id)
        if item is None or item["state"] == ItemState.DONE:
            # Completing something already done must not mint another copy.
            return None

        rule = recurrence.rule_from_row(item)
        if not rule.is_recurring:
            return None

        today = date.today()
        if rule.anchor == recurrence.RepeatFrom.COMPLETION:
            anchor = today
        else:
            # Keep the planned cadence: prefer the date this occurrence was
            # actually meant for, and fall back to today if it had none.
            planned = item["defer_until"] or item["due_date"]
            anchor = date.fromisoformat(planned) if planned else today

        try:
            following = recurrence.next_occurrence(rule, anchor=anchor, today=today)
        except recurrence.RecurrenceError:
            # A malformed rule must not block completing the task.
            return None
        if following is None:
            return None

        values = {field: item[field] for field in self._RECURRING_FIELDS}
        values["state"] = str(ItemState.NEXT_ACTION)
        values["defer_until"] = following.isoformat()
        # A deadline travels with the occurrence; without this a monthly bill
        # would keep the first month's due date forever.
        values["due_date"] = following.isoformat() if item["due_date"] else None
        values["recurs_from_id"] = item_id

        now = _now()
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        with self.db.connect() as conn:
            cur = conn.execute(
                f"""INSERT INTO items ({columns}, created_at, updated_at)
                    VALUES ({placeholders}, ?, ?)""",
                (*values.values(), now, now),
            )
            return cur.lastrowid

    def set_recurrence(
        self,
        item_id: int,
        *,
        every: int | None = None,
        unit: str | None = None,
        days: set[str] | frozenset[str] | None = None,
        anchor: str = recurrence.RepeatFrom.SCHEDULE,
    ) -> None:
        """Set or clear an item's repeat rule.

        Interval and day-of-week are mutually exclusive; setting one clears the
        other, so a rule can never be half of each.
        """
        stored_days = recurrence.format_days(days)
        if stored_days:
            every, unit = None, None
        elif every is not None and unit is not None:
            if every < 1:
                raise ValueError("repeat interval must be at least 1")
            if unit not in {str(u) for u in recurrence.RepeatUnit}:
                raise ValueError(f"unknown repeat unit: {unit}")
        else:
            every, unit = None, None

        repeats = bool(stored_days or (every and unit))
        self.update_item(
            item_id,
            repeat_every=every,
            repeat_unit=unit,
            repeat_days=stored_days,
            repeat_from=str(anchor) if repeats else None,
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
                      a.name AS area_name, a.emoji AS area_emoji,
                      (SELECT GROUP_CONCAT(pr.title, ' · ')
                         FROM item_dependencies d
                         JOIN items pr ON pr.id = d.prerequisite_item_id
                        WHERE d.blocked_item_id = i.id
                          AND pr.state != 'done') AS blocked_by_titles
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

    # ── Ordered lists ────────────────────────────────────────────────────────
    #
    # Books, checklists and technology projects share one shape: an ordered,
    # categorised list sitting outside the actionable flow. What they need that
    # ordinary items lack is a *rank* — sequence within a group. Rank is not
    # priority: priority is P1-P3 importance and sorts every list the same way,
    # while rank means nothing except relative to its neighbours in one group.
    #
    # The grouping column differs per feature (books rank within a category,
    # checklist items within their checklist), so it is a parameter rather than
    # baked in. Each feature adds its column to RANK_GROUPS as it lands.

    @staticmethod
    def _check_rank_group(group: str | None) -> None:
        """`group` becomes a column name in SQL, which parameter binding cannot
        do for us, so it is checked against a whitelist rather than trusted.

        Callers validate *before* reading the column off a row — otherwise a bad
        name fails as a row-lookup error and the whitelist stops being the thing
        that reports the problem.
        """
        if group is not None and group not in RANK_GROUPS:
            raise ValueError(f"not a rank grouping column: {group}")

    def _rank_scope(
        self, state: str, group: str | None, group_value: Any
    ) -> tuple[str, list[Any]]:
        """SQL predicate isolating the one ordered list an item belongs to."""
        self._check_rank_group(group)
        if group is None:
            return "state = ?", [str(state)]
        if group_value is None:
            return f"state = ? AND {group} IS NULL", [str(state)]
        return f"state = ? AND {group} = ?", [str(state), group_value]

    def _ensure_ranks(self, conn: sqlite3.Connection, where: str, params: list[Any]) -> None:
        """Give every row in one group a rank, preserving how it currently reads.

        Items arrive in an ordered list unranked — captured before the list
        existed, or added without anyone caring about sequence yet. Rather than
        refuse to reorder those, materialise ranks on first use.
        """
        rows = conn.execute(
            f"""SELECT id, "rank" FROM items WHERE {where}
                ORDER BY CASE WHEN "rank" IS NULL THEN 1 ELSE 0 END, "rank" ASC,
                         created_at ASC, id ASC""",
            params,
        ).fetchall()
        for position, row in enumerate(rows):
            if row["rank"] != position:
                conn.execute(
                    'UPDATE items SET "rank" = ? WHERE id = ?', (position, row["id"])
                )

    def list_ordered(
        self, state: str, *, group: str | None = None, group_value: Any = None
    ) -> list[sqlite3.Row]:
        """One ordered list, in rank order.

        Unranked items sort last by age rather than disappearing, so a list
        nobody has sequenced yet still reads sensibly.
        """
        where, params = self._rank_scope(state, group, group_value)
        with self.db.connect() as conn:
            return conn.execute(
                f"""SELECT * FROM items WHERE {where}
                    ORDER BY CASE WHEN "rank" IS NULL THEN 1 ELSE 0 END, "rank" ASC,
                             created_at ASC, id ASC""",
                params,
            ).fetchall()

    def append_to_ordered(
        self, title: str, state: str, *, group: str | None = None, **fields: Any
    ) -> int:
        """Add an item to the end of an ordered list."""
        self._check_rank_group(group)
        item_id = self.capture(title, state=state)
        group_value = fields.get(group) if group else None
        where, params = self._rank_scope(state, group, group_value)
        with self.db.connect() as conn:
            row = conn.execute(
                f'SELECT MAX("rank") AS top FROM items WHERE {where}', params
            ).fetchone()
            last = row["top"]
        self.update_item(item_id, rank=0 if last is None else last + 1, **fields)
        return item_id

    def move_in_order(self, item_id: int, delta: int, *, group: str | None = None) -> bool:
        """Move an item one place up (-1) or down (+1) within its ordered list.

        Returns False when it is already at the end it is being moved toward —
        the caller can redirect either way, but a no-op should not read as a
        successful move.
        """
        if delta not in (-1, 1):
            raise ValueError("delta must be -1 or 1")
        self._check_rank_group(group)
        item = self.get_item(item_id)
        if item is None:
            return False

        group_value = item[group] if group else None
        where, params = self._rank_scope(item["state"], group, group_value)
        with self.db.connect() as conn:
            self._ensure_ranks(conn, where, params)
            current = conn.execute(
                'SELECT "rank" FROM items WHERE id = ?', (item_id,)
            ).fetchone()["rank"]

            # The neighbour is whichever row is adjacent in the direction of
            # travel, not current ± 1: ranks are only guaranteed ordered, and a
            # deleted row can leave a gap.
            comparison, order = ("<", "DESC") if delta < 0 else (">", "ASC")
            neighbour = conn.execute(
                f'''SELECT id, "rank" FROM items
                    WHERE {where} AND "rank" {comparison} ?
                    ORDER BY "rank" {order} LIMIT 1''',
                (*params, current),
            ).fetchone()
            if neighbour is None:
                return False

            conn.execute(
                'UPDATE items SET "rank" = ? WHERE id = ?', (neighbour["rank"], item_id)
            )
            conn.execute(
                'UPDATE items SET "rank" = ? WHERE id = ?', (current, neighbour["id"])
            )
        return True

    # ── Books ────────────────────────────────────────────────────────────────
    #
    # Books are an ordered list specialised with progress fields. They rank
    # within their category, and each category orders independently.
    #
    # Books deliberately do NOT generate next actions or link to projects. If a
    # book needs an action ("finish ch. 3"), that is captured as an ordinary
    # task through the normal flow. Keeping the two apart is what makes this a
    # small feature rather than a second project system.

    def add_book(
        self,
        title: str,
        *,
        book_category: str,
        is_audio: bool = False,
        started: bool = False,
    ) -> int:
        """Add a book to the end of its category."""
        return self.append_to_ordered(
            title,
            ItemState.BOOK,
            group="book_category",
            book_category=str(book_category),
            is_audio=1 if is_audio else 0,
            started=1 if started else 0,
            started_on=_today() if started else None,
            percent_complete=0,
        )

    def restore_book(self, item_id: int) -> bool:
        """Put a finished book back on its shelf, at the end of its category.

        Undoing a completion has to know what the item *was*. Books are not in
        `user_lists()`, so the generic restore would drop one into Next Actions
        — a book masquerading as an action. It also gets a fresh rank rather
        than its old one, which may since have been reused by a live book.
        """
        item = self.get_item(item_id)
        if item is None or not item["book_category"]:
            return False

        where, params = self._rank_scope(
            ItemState.BOOK, "book_category", item["book_category"]
        )
        with self.db.connect() as conn:
            top = conn.execute(
                f'SELECT MAX("rank") AS top FROM items WHERE {where}', params
            ).fetchone()["top"]
            conn.execute(
                """UPDATE items
                      SET state = ?, "rank" = ?, completed_at = NULL, updated_at = ?
                    WHERE id = ?""",
                (str(ItemState.BOOK), 0 if top is None else top + 1, _now(), item_id),
            )
        return True

    def list_books(self) -> list[sqlite3.Row]:
        """Every unfinished book, in category then rank order.

        Finished books are gone from here — completing moves them to `done` like
        anything else, so the reading page shows only what is actually live.
        """
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT * FROM items WHERE state = ?
                   ORDER BY book_category ASC,
                            CASE WHEN "rank" IS NULL THEN 1 ELSE 0 END, "rank" ASC,
                            created_at ASC, id ASC""",
                (str(ItemState.BOOK),),
            ).fetchall()

    def set_book_progress(
        self,
        item_id: int,
        *,
        percent_complete: int | None = None,
        started: bool | None = None,
        is_audio: bool | None = None,
    ) -> None:
        """Update progress fields, leaving anything not passed alone."""
        fields: dict[str, Any] = {}
        if percent_complete is not None:
            fields["percent_complete"] = int(percent_complete)
        if is_audio is not None:
            fields["is_audio"] = 1 if is_audio else 0
        if started is not None:
            fields["started"] = 1 if started else 0
            # A start date is only meaningful while started; un-starting clears
            # it rather than leaving a date that contradicts the flag.
            existing = self.get_item(item_id)
            if started and not (existing and existing["started_on"]):
                fields["started_on"] = _today()
            elif not started:
                fields["started_on"] = None
        if fields:
            self.update_item(item_id, **fields)

    # ── Checklists ───────────────────────────────────────────────────────────
    #
    # A checklist is a container, so it gets a table — `evergreen` and a
    # one-off's completion are properties of the list as a whole, not of any
    # item in it. Membership still lives in `items`, ranked within the list.
    #
    # The two kinds differ only in their terminal action:
    #   evergreen -> reset, clearing ticks. It is run again and never completes.
    #   one-off   -> complete, and it leaves the page. It is never reset.
    #
    # `ticked` is checklist-local and deliberately NOT the `done` state. If
    # ticking moved an item to Done, reset would have to resurrect rows out of
    # `done`, and packing a bag would litter the Done list.

    def create_checklist(self, name: str, *, evergreen: bool = True) -> int:
        name = name.strip()
        if not name:
            raise ValueError("name cannot be empty")
        now = _now()
        with self.db.connect() as conn:
            cur = conn.execute(
                """INSERT INTO checklists (name, evergreen, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (name, 1 if evergreen else 0, str(ChecklistStatus.ACTIVE), now, now),
            )
            return cur.lastrowid

    def get_checklist(self, checklist_id: int) -> sqlite3.Row | None:
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT * FROM checklists WHERE id = ?", (checklist_id,)
            ).fetchone()

    def list_checklists(
        self, status: str | None = ChecklistStatus.ACTIVE
    ) -> list[sqlite3.Row]:
        """Checklists with their item and tick counts, so the index can show
        progress without a query per row."""
        sql = [
            """SELECT c.*,
                      (SELECT COUNT(*) FROM items i
                        WHERE i.checklist_id = c.id AND i.state = 'checklist') AS item_count,
                      (SELECT COUNT(*) FROM items i
                        WHERE i.checklist_id = c.id AND i.state = 'checklist'
                          AND i.ticked = 1) AS ticked_count
                 FROM checklists c"""
        ]
        params: list[Any] = []
        if status is not None:
            sql.append("WHERE c.status = ?")
            params.append(str(status))
        sql.append("ORDER BY c.evergreen DESC, c.name ASC")
        with self.db.connect() as conn:
            return conn.execute(" ".join(sql), params).fetchall()

    def update_checklist(self, checklist_id: int, **fields: Any) -> None:
        allowed = {"name", "evergreen", "notes"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unknown field(s): {', '.join(sorted(unknown))}")
        if not fields:
            return
        if "name" in fields and not str(fields["name"]).strip():
            raise ValueError("name cannot be empty")

        values = []
        for k, v in fields.items():
            if k == "evergreen":
                values.append(1 if v else 0)
            else:
                values.append(str(v).strip())
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE checklists SET {sets}, updated_at = ? WHERE id = ?",
                (*values, _now(), checklist_id),
            )

    def delete_checklist(self, checklist_id: int) -> None:
        """Removes the list and its items — the FK cascades."""
        with self.db.connect() as conn:
            conn.execute("DELETE FROM checklists WHERE id = ?", (checklist_id,))

    def add_checklist_item(self, checklist_id: int, title: str) -> int:
        return self.append_to_ordered(
            title,
            ItemState.CHECKLIST,
            group="checklist_id",
            checklist_id=checklist_id,
        )

    def list_checklist_items(self, checklist_id: int) -> list[sqlite3.Row]:
        return self.list_ordered(
            ItemState.CHECKLIST, group="checklist_id", group_value=checklist_id
        )

    def set_ticked(self, item_id: int, ticked: bool) -> None:
        self.update_item(item_id, ticked=1 if ticked else 0)

    def reset_checklist(self, checklist_id: int) -> bool:
        """Clear the ticks and nothing else — items, order and membership stay.

        Only meaningful for an evergreen list; a one-off is completed instead of
        being run again.
        """
        checklist = self.get_checklist(checklist_id)
        if checklist is None or not checklist["evergreen"]:
            return False
        with self.db.connect() as conn:
            conn.execute(
                """UPDATE items SET ticked = 0, updated_at = ?
                    WHERE checklist_id = ? AND state = ?""",
                (_now(), checklist_id, str(ItemState.CHECKLIST)),
            )
        return True

    def complete_checklist(self, checklist_id: int) -> bool:
        """Finish a one-off. Evergreen lists never complete — they reset."""
        checklist = self.get_checklist(checklist_id)
        if checklist is None or checklist["evergreen"]:
            return False
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                """UPDATE checklists
                      SET status = ?, completed_at = ?, updated_at = ?
                    WHERE id = ?""",
                (str(ChecklistStatus.DONE), now, now, checklist_id),
            )
        return True

    def reopen_checklist(self, checklist_id: int) -> None:
        now = _now()
        with self.db.connect() as conn:
            conn.execute(
                """UPDATE checklists
                      SET status = ?, completed_at = NULL, updated_at = ?
                    WHERE id = ?""",
                (str(ChecklistStatus.ACTIVE), now, checklist_id),
            )

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

    # ── Item dependencies ───────────────────────────────────────────────────

    def _would_create_dependency_cycle(
        self, conn: sqlite3.Connection, blocked_item_id: int, prerequisite_item_id: int
    ) -> bool:
        row = conn.execute(
            """WITH RECURSIVE deps(id) AS (
                   SELECT prerequisite_item_id
                     FROM item_dependencies
                    WHERE blocked_item_id = ?
                   UNION
                   SELECT d.prerequisite_item_id
                     FROM item_dependencies d
                     JOIN deps ON d.blocked_item_id = deps.id
               )
               SELECT 1 FROM deps WHERE id = ? LIMIT 1""",
            (prerequisite_item_id, blocked_item_id),
        ).fetchone()
        return row is not None

    def add_dependency(self, blocked_item_id: int, prerequisite_item_id: int) -> None:
        """Track that one item is waiting for another item to finish.

        Blocked work belongs in Waiting For: it is a real commitment, but not
        something the user can engage with until the prerequisite clears.
        """
        if blocked_item_id == prerequisite_item_id:
            raise ValueError("an item cannot depend on itself")

        now = _now()
        with self.db.connect() as conn:
            blocked = conn.execute(
                "SELECT id FROM items WHERE id = ?", (blocked_item_id,)
            ).fetchone()
            prerequisite = conn.execute(
                "SELECT id FROM items WHERE id = ?", (prerequisite_item_id,)
            ).fetchone()
            if blocked is None or prerequisite is None:
                raise ValueError("dependency item not found")
            if self._would_create_dependency_cycle(conn, blocked_item_id, prerequisite_item_id):
                raise ValueError("dependency would create a cycle")

            conn.execute(
                """INSERT OR IGNORE INTO item_dependencies
                   (blocked_item_id, prerequisite_item_id, created_at)
                   VALUES (?, ?, ?)""",
                (blocked_item_id, prerequisite_item_id, now),
            )
            conn.execute(
                "UPDATE items SET state = ?, updated_at = ? WHERE id = ?",
                (str(ItemState.WAITING_FOR), now, blocked_item_id),
            )

    def replace_dependencies(
        self, blocked_item_id: int, prerequisite_item_ids: Sequence[int]
    ) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "DELETE FROM item_dependencies WHERE blocked_item_id = ?",
                (blocked_item_id,),
            )
        for prerequisite_item_id in prerequisite_item_ids:
            self.add_dependency(blocked_item_id, prerequisite_item_id)

    def list_dependencies(self, blocked_item_id: int) -> list[sqlite3.Row]:
        with self.db.connect() as conn:
            return conn.execute(
                """SELECT d.*, p.title AS prerequisite_title, p.state AS prerequisite_state
                   FROM item_dependencies d
                   JOIN items p ON p.id = d.prerequisite_item_id
                   WHERE d.blocked_item_id = ?
                   ORDER BY p.title""",
                (blocked_item_id,),
            ).fetchall()

    def list_dependency_candidates(
        self, *, blocked_item_id: int | None = None
    ) -> list[sqlite3.Row]:
        sql = [
            """SELECT i.*, p.name AS project_name
               FROM items i
               LEFT JOIN projects p ON p.id = i.project_id
               WHERE i.state IN (?, ?)"""
        ]
        params: list[Any] = [str(ItemState.NEXT_ACTION), str(ItemState.WAITING_FOR)]
        if blocked_item_id is not None:
            sql.append("AND i.id != ?")
            params.append(blocked_item_id)
        sql.append("ORDER BY i.title")
        with self.db.connect() as conn:
            return conn.execute(" ".join(sql), params).fetchall()

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
                          AS open_actions,
                        (SELECT COUNT(*) FROM items i
                          WHERE i.project_id = p.id AND i.state = 'waiting_for')
                          AS waiting_items
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

# Fixed Bugs

Concrete defects that were observed, fixed, and covered by regression tests.
Use this for bug history and verification notes. Use `ADR.md` for higher-level
architecture decisions.

---

## 2026-08-24 — Waiting For could only describe task dependencies as text

**Symptom.** A dependent task such as `Eat cookies` could be put on Waiting For
with `waiting_on = "Buy cookies"`, but that text was not linked to the real
`Buy cookies` item. The UI could not distinguish a task blocker from a person,
and completing `Buy cookies` did not make `Eat cookies` actionable.

**Cause.** Waiting For used one free-text `waiting_on` field for every kind of
waiting. There was no item-to-item dependency model.

**Fix.** Added `item_dependencies` with `blocked_item_id` and
`prerequisite_item_id`. Waiting For now shows task blockers as "blocked by ..."
while keeping delegated waits as "waiting on ...". Completing a prerequisite
promotes blocked waiting items to Next Actions once all blockers are done.

**Regression tests.**

- `test_waiting_item_can_be_blocked_by_another_item`
- `test_completing_a_prerequisite_unblocks_waiting_items`
- `test_dependency_rejects_self_blocking`
- `test_dependency_rejects_cycles`
- `test_direct_add_waiting_for_can_be_blocked_by_a_task`
- `test_waiting_page_distinguishes_task_blockers_from_people`
- `test_completing_blocker_promotes_waiting_item`
- `test_edit_can_assign_a_blocking_task`
- `test_project_with_waiting_item_is_not_stalled_without_next_action`

## 2026-08-30 — Running the test suite mutated the live database

**Symptom.** `uv run pytest` from the repo root silently migrated the real
`gtd.db` from schema v2 to v3. Caught by hashing the file across a run.

**Cause.** `gtd/web.py` creates its app at import (`app = create_app()`), which
calls `init_schema()` against whatever `GTD_DB_PATH` resolves to — and it
defaults to `gtd.db` *relative to the working directory*. Importing `gtd.web`
had always opened the live database; it was harmless only while `init_schema`
did nothing but `CREATE TABLE IF NOT EXISTS`. Adding migrations made the same
import start altering real data.

**Fix.** `tests/conftest.py` redirects `GTD_DB_PATH` to a temp file before any
test module is imported. Verified by comparing the md5 of `gtd.db` before and
after a full run.

**Regression test.** None directly — a test asserting "the suite did not write
to a path outside tmp" would have to run the suite. The guard lives in
`conftest.py` with a comment explaining why it must not be removed, and the
hazard is recorded in `AGENTS.md`.

## 2026-08-30 — A schema bump moved the version number without migrating

**Symptom.** Adding a column to `SCHEMA` reached fresh installs only. An
existing database reported itself as the new version while still missing the
column.

**Cause.** `init_schema` ran `CREATE TABLE IF NOT EXISTS` and then updated
`schema_version`, with nothing in between. `CREATE TABLE IF NOT EXISTS` is a
no-op where the table already exists, so no column was ever added.

**Fix.** Added `MIGRATIONS` in `db.py`, applied for each version between the
stored one and `SCHEMA_VERSION`.

**Regression test.**

- `test_migrating_from_each_previous_version_reaches_existing_data` —
  parameterised over every upgrade path, building a database at the previous
  version with rows in it. Its fixtures are derived from `MIGRATIONS` rather
  than hardcoded, after an earlier version of this test stopped testing
  anything once a second migration arrived.

## 2026-08-30 — An index over a not-yet-added column crashed startup

**Symptom.** With the v5 checklist work in place, `init_schema` raised
`sqlite3.OperationalError: no such column: checklist_id` on any existing
database. Startup would have failed for the live instance.

**Cause.** `SCHEMA` created `idx_items_checklist` in the same script as the
tables, so the index ran before the migration that adds `checklist_id`. On a
fresh database the column exists already and it works; on an existing one the
`CREATE TABLE IF NOT EXISTS` is a no-op and the column is still missing.

**Fix.** Split `SCHEMA_INDEXES` out of `SCHEMA` and apply it *after* migrations.

**Regression test.** Covered by
`test_migrating_from_each_previous_version_reaches_existing_data`, which is what
caught it. Additionally verified by migrating a copy of the live database from
v4 to v5 with its rows in place.

## 2026-08-30 — A finished book could not be put back on its shelf

**Symptom.** Restoring a completed book from the Done list filed it as a Next
Action rather than returning it to `/books`.

**Cause.** `/items/{id}/restore` only accepts a target state in
`ItemState.user_lists()`, and `BOOK` is deliberately excluded from that set
because books have their own page. Books fell through to the `next_action`
default.

**Fix.** `restore_book()` returns a book to its shelf and clears `completed_at`.
It appends rather than reinstating the old rank, because a finished book keeps
its rank and a later book reuses it — real data had three finished fiction books
all at rank 0.

**Regression tests.**

- `test_restoring_a_finished_book_returns_it_to_its_shelf`
- `test_a_restored_book_does_not_collide_with_a_live_rank`
- `test_restore_route_sends_a_book_home_not_to_next_actions`
- `test_restore_still_works_normally_for_non_books`

## 2026-09-04 — Importing `gtd.web` migrated the live database, again

**Symptom.** A `python -c "import gtd.web"` syntax check, run from the repo
root, silently migrated the live `gtd.db` from v5 to v6.

**Cause.** The same root cause as the 2026-08-30 test-suite entry: `web.py` ran
`app = create_app()` at module level, and `create_app` calls `init_schema()`
against whatever `GTD_DB_PATH` resolves to — `./gtd.db` by default. The earlier
fix only redirected the path for *tests*; every other import remained live.

**Fix.** `app` is now built lazily via a module-level `__getattr__` (PEP 562).
`uvicorn gtd.web:app` still works, because attribute access triggers it, but
importing the module no longer touches any database.

Documenting the hazard was not sufficient — it was written up in `AGENTS.md`
and then walked into anyway. The import is now inert by construction.

**Regression test.** `test_importing_web_does_not_touch_a_database`, which
imports the module in a subprocess with `GTD_DB_PATH` pointed at a path that
must not come into existence.

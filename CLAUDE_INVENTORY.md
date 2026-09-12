# Claude inventory — what an AI session changed, and why

Provenance record. A future session (human or agent) can use this to tell which
files were authored or altered by Claude Code, in which commits, and for what
reason. It is not a changelog — `git log` is that. It is a **signature**.

---

## Session: 2026-08-30 → 2026-09-12

**Agent:** Claude Code (Opus), session `01BS2oPoZytacDJNV6jRDuTc`
**Commits:** 26, all carrying `Co-Authored-By: Claude`
**Range:** `749412f` … `7bb8040`
**State at signing:** working tree clean, in sync with `origin/main`

### What was done, and why

**Ordered lists, then three features on top.** Books, checklists and technology
projects were specced in `HUMAN_PLANS.md` as one concept: an ordered,
categorised list *outside* the actionable flow. Built as `items.rank` — sequence
within a group, distinct from `priority` — then specialised three times.
See ADR-012 and ADR-013.

**Recurring tasks.** A repeat rule spawns the next occurrence on completion,
riding the existing `defer_until` tickler rather than introducing a scheduler.
Days are individual (`mon`…`sun`) after the group model failed a real case:
bin day is a Wednesday. See ADR-015.

**Backups, because there were none.** `tmutil` reported no Time Machine
destination and `exports/` is lossy markdown. `gtd backup` takes verified
snapshots with `VACUUM INTO`, copies them to a second machine, and optionally
encrypts for cloud. Constraint 4 was read as *no third party holds the data*
rather than *no bytes move* — recorded as ADR-014 rather than assumed.

**Navigation and search.** The nav had grown to thirteen entries; it is now four,
with everything else on `/lists`. Search did not exist and now does. `/daily`
separates standing habits from tasks.

### Files created by Claude

```
src/gtd/backup.py                     src/gtd/templates/books.html
src/gtd/recurrence.py                 src/gtd/templates/checklist.html
Daily_Briefing_Agent.md               src/gtd/templates/checklists.html
tests/test_backup.py                  src/gtd/templates/daily.html
tests/test_books.py                   src/gtd/templates/lists.html
tests/test_checklists.py              src/gtd/templates/list_new.html
tests/test_daily_and_search.py        src/gtd/templates/search.html
tests/test_navigation.py              src/gtd/templates/tech.html
tests/test_ordered_lists.py
tests/test_recurrence.py
tests/test_recurring_tasks.py
tests/test_tech_projects.py
```

### Files modified by Claude

```
ADR.md  AGENTS.md  FIXED_BUGS.md  HUMAN_PLANS.md  README.md
.env.example  .gitignore
src/gtd/: cli.py  config.py  db.py  export.py  models.py  store.py  web.py
          static/style.css
          templates/: base.html  clarify.html  edit.html  list.html
tests/: conftest.py  test_export.py  test_web.py
```

### Not Claude's

Everything else, including the whole pre-2026-08-30 codebase: the app itself,
the clarify flow, auth, the local-only guard, ADR-001 through ADR-011.

### Things a future session should not undo

- **`tests/conftest.py` redirects `GTD_DB_PATH`.** Without it, running the suite
  from the repo root migrates the *live* database. That happened twice.
- **`gtd.web.app` is built lazily** via module-level `__getattr__`. Restoring
  eager `app = create_app()` reintroduces the same hazard for any import.
- **Indexes live in `SCHEMA_INDEXES` and run after migrations.** Merging them
  back into `SCHEMA` crashes startup on any existing database.
- **`ticked` is not the `done` state**, and books/checklists/tech never generate
  next actions. Both are load-bearing, not stylistic.

### Known-wrong things this session produced and then fixed

Recorded honestly because they shape trust in the rest: a regression test that
passed with its bug still present (caught by deliberately re-breaking the code);
a corrupted README line committed and pushed (`112b377`, fixed in `55add01`); and
two accidental migrations of the live database, which is why the two guards above
exist.

---

## Code review of this session's work

Reviewed as a PR, by the author. Findings verified against the code, not recalled.

### Strengths

- **Every change is grounded in an observed failure**, and the failure is recorded
  next to the fix. `FIXED_BUGS.md` states plainly where a fix has no test.
- **Tests assert behaviour, not implementation.** Several were mutation-checked —
  the code was deliberately re-broken to confirm the test fails. That caught one
  test that was passing with its bug still present.
- **Migrations were proven against copies of the live database** before the live
  one was touched, at every schema bump from v3 to v7.
- **Date arithmetic is isolated** in `recurrence.py` with no database access, so
  month-end clamping and leap years are cheap to test exhaustively.
- **Guards refuse rather than degrade**: a cloud backup with no recipient exits
  non-zero instead of uploading plaintext; `restore` refuses a file that is valid
  SQLite but not a GTD database.

### Flaws — ordered by how much they would cost to hit

**1. `backup.push()` has a wrong default that silently disables a safety check.**
`source_db or snapshot` (`backup.py:199`) means a caller who omits `source_db`
gets the *snapshot* compared against the destination instead of the database. The
same-device guard then answers the wrong question. It usually still fires,
because snapshots live beside the database — but "usually" is not what a guard
against silent data loss should be. `source_db` should be required.

**2. `store.daily_items()` reaches into `recurrence` internals.**
`recurrence._WEEKDAY_NUMBERS` (`store.py:773,775`) is private and accessed across
a module boundary. The store now breaks if recurrence renames a lookup table.
This should be a public `covers_weekday(rule, day)` on `recurrence`.

**3. `describe()` compares a day set to dictionary keys.**
`rule.days == frozenset(_WEEKDAY_NUMBERS)` works only because `StrEnum` members
compare equal to their strings. Display logic is coupled to an internal lookup
table; an explicit `ALL_DAYS` constant would say what is meant.

**4. The recurrence UI has no rendering test in the suite.**
Its defaults, the seven checkboxes and the mode picker were verified by hand
against a live server. Everything else in this session got a route test; this did
not, and it is the most intricate form in the app.

**5. Leftover scaffolding.** `test_navigation.py` has a stray `app=None`
parameter on a test that does not use it.

### What I would ask for before merging

Fix (1) — it is a safety guard that does not always guard. (2) and (3) are
tidiness with a real failure mode behind them. (4) is the honest gap: a form that
complex deserves a test asserting what it renders.

---

*Signed: Claude Code, 2026-09-12. Verified against `git log --grep="Co-Authored-By: Claude"` at signing time.*

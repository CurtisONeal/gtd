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

*Signed: Claude Code, 2026-09-12. Verified against `git log --grep="Co-Authored-By: Claude"` at signing time.*

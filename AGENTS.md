# AGENTS.md — context for AI coding agents

Read this before changing anything. `ADR.md` has the reasoning behind the
decisions below; this file is the operating rules. **If you are an agent
trying to READ GTD data (a briefing, a review, a report), read
`Daily_Briefing_Agent.md` first — there is no read API, and the obvious
approach does not work.** `GTD_METHOD.md` has the
David Allen GTD method context behind the product behavior; read it before
changing capture, clarify, list organization, project review, or engagement
behavior.

## What this is

A self-hosted Getting Things Done system. Single user. Python 3.11, FastAPI,
SQLite, server-rendered Jinja2. It exists because the app it replaces kept
personal data in a third-party spreadsheet with no real auth.

## Hard constraints — do not violate without an explicit decision

1. **No LLM calls in the core.** Capture, clarify, list management and export are
   deterministic code. Model calls are reserved for judgment — coaching, weekly
   review, priority suggestions — and none of that is built yet. Do not add an
   API call to move a row between lists.

2. **No JavaScript dependencies.** Zero. No framework, no HTMX, no CDN, no
   vendored bundle, no build step. Interactivity is server-rendered forms with
   POST-redirect-GET. If something seems to need JS, it probably needs a
   different page instead. See ADR-002.

3. **All SQL lives in `store.py`.** No queries in `web.py`, `cli.py`, or
   templates. This is what keeps a Postgres migration viable. See ADR-003.

4. **Nothing leaves the machine.** No telemetry, no third-party API, no external
   asset loads (fonts, scripts, images). The data is the point.

5. **Never commit `.env`, `*.db`, or `exports/`.** All gitignored. This repo is
   public — verify before every push.

6. **Never set or store a user's password in code, config, or a commit.** Only
   `gtd set-password` creates one, interactively.

7. **Work deployments are local-only, permanently.** `127.0.0.1`, no Tailscale,
   no tunnel, no reverse proxy, no inbound exposure. This is the deployment mode
   for work instances, not a default to relax later. Do not add features that
   assume a work instance is reachable from elsewhere, and do not build bridges
   between a work instance and a personal one. See ADR-008.

8. **Do not weaken the `GTD_LOCAL_ONLY` guard.** It is enforced in two places
   (`gtd serve` refuses a public bind; the outermost middleware rejects
   non-loopback peers). Never read the peer address from `X-Forwarded-For` or
   any other header — it must come from the socket. If a test fails against it,
   fix the test, not the check: `TestClient` reports its peer as the literal
   string `"testclient"`, which is correctly treated as non-local. See ADR-010.

## Design principles

- **Capture must be frictionless.** `capture()` takes a title and nothing else.
  Metadata is a *clarify*-time concern. Do not add required fields to capture.
- **Capture-then-clarify is primary, but not the only route.** Next Actions,
  Waiting For, Someday and Reference each have a direct-add form for when the
  destination is already known; the edit page can move anything anywhere. Done
  and Trash are outcomes and take no direct add. See ADR-009.
- **Every list is a `state` of `items`.** Adding a list means adding an enum
  value, not a table. See ADR-001.
- **Soft delete by default.** `delete_item()` sets `trashed`; hard delete is
  opt-in. Undo should always be possible.
- **Disclose, don't hide.** The tickler withholds deferred items from next
  actions — and the page says how many it is withholding. Silent filtering is a
  bug.
- **Blocked items are Waiting For items.** Use real item dependencies for
  internal blockers and `waiting_on` text for delegated/external waits. Do not
  create a separate blocked list or match dependencies by title. See ADR-011.
- **Match the method.** This implements David Allen's GTD as specified: the
  clarify decision tree, the two-minute rule, contexts, the four-criteria model
  (context / time / energy / priority). If a change would drift from the method,
  say so explicitly rather than quietly reinterpreting it. See `GTD_METHOD.md`.

## Layout

```
src/gtd/
├── config.py    env-driven settings; nothing hardcoded to localhost
├── db.py        connection + schema + MIGRATIONS (plain sqlite3, WAL)
├── models.py    ItemState / Energy / ProjectStatus / ChecklistStatus /
│                BookCategory / Source / TIME_ESTIMATES / PERCENT_BUCKETS
├── store.py     repository layer — ALL SQL
├── auth.py      argon2id hashing, session key, login rate limiter
├── export.py    markdown export
├── cli.py       argparse entry point
├── web.py       FastAPI app + routes
├── templates/   base, login, index, clarify, list, edit, projects,
│                books, checklists, checklist, tech
└── static/      style.css — the entire frontend
```

## Recurring tasks

A next action can carry a repeat rule; completing it files it under Done and
inserts the next occurrence with `defer_until` set. See ADR-015 and
`recurrence.py`, which is pure date arithmetic and deliberately has no database
access.

- **It rides the tickler, not a scheduler.** There is no background job. The
  successor is an ordinary Next Action hidden until its date.
- **Never backfill.** Finishing late produces one occurrence, not the whole
  missed run. `next_occurrence` is always strictly after today.
- **Month-ends clamp.** 31 January + 1 month is 28 February. Rolling over would
  push a monthly task later on every repeat.
- **Dependencies and `waiting_on` do not carry forward** — a prerequisite
  satisfied once must not be recreated, or the successor appears pre-blocked.
- Days are stored as a comma set of `mon`…`sun`. `describe()` collapses the
  common shapes into "every weekday" / "every weekend" / "every day".

## Ordered lists

Books, checklists and technology projects are one concept: an ordered,
categorised list *outside* the actionable flow. They share `items.rank` —
sequence within a group, which is not `priority` (P1-P3 importance). See
ADR-012 and ADR-013.

- The grouping column is a parameter, whitelisted in `RANK_GROUPS`, because it
  is interpolated into SQL as a column name. Validate before reading it off a
  row.
- Ranks are ordered but **not contiguous**. Find a neighbour by comparison, not
  `rank ± 1` — a deleted row leaves a gap by design.
- Unranked rows sort last and materialise a rank on first move, so data that
  predates a list stays usable.
- Checklists have a container table because `evergreen` and a one-off's
  completion belong to the list, not its items. `ticked` is checklist-local and
  is **never** the `done` state, or reset would have to resurrect rows.
- None of these generate next actions. Keep it that way; it is what stops the
  feature becoming a second project system.

## Gotchas that have already bitten

- **Middleware order.** Starlette applies middleware in *reverse* registration
  order, so the last registered is outermost. `SessionMiddleware` must be added
  *after* the auth-gate middleware, or `request.session` will not exist when the
  gate runs.
- **`_clean()` turns `""` into `NULL`.** Correct for optional columns, fatal for
  `NOT NULL` ones. `update_item()` keeps a string for `title`, `notes`, `state`,
  `source`.
- **Timestamps need microsecond precision.** A brain dump creates many items in
  the same second; second-precision timestamps tie and break FIFO ordering.
- **`gtd.web.app` is built lazily — keep it that way.** It used to be
  `app = create_app()` at module level, which calls `init_schema()` against
  whatever `GTD_DB_PATH` resolves to (`gtd.db` relative to the working
  directory). Once `init_schema` applied migrations, *any* import from the repo
  root altered the live database — a test collecting, a syntax check. That
  happened twice, the second time after the hazard was already written down
  here. `web.py` now builds the app in a module-level `__getattr__`, so
  `uvicorn gtd.web:app` works and a bare import does nothing. Do not restore
  eager construction. `tests/conftest.py` also redirects `GTD_DB_PATH`; that is
  belt and braces, keep both.
- **Adding a column means adding a migration.** `CREATE TABLE IF NOT EXISTS` is
  a no-op on an existing database, so a column added only to `SCHEMA` reaches
  fresh installs and nothing else. Bump `SCHEMA_VERSION` and add the statement
  to `MIGRATIONS` in `db.py`, then prove it against a database built at the
  previous version — see
  `test_migrating_from_each_previous_version_reaches_existing_data`, which is
  parameterised over every upgrade path and derives its fixtures from
  `MIGRATIONS` so it cannot quietly stop testing anything.
- **Indexes go in `SCHEMA_INDEXES`, never with the tables.** They are applied
  *after* migrations. An index over a column a migration is about to add will
  fail on every existing database, because the table already exists and the
  column does not yet. This crashed startup once and was caught only by the
  migration test.
- **A new NOT NULL flag needs adding to `boolean` in `update_item`.** An
  unchecked checkbox sends nothing at all, and `_clean` would turn that blank
  into `NULL`. Same trap as the text columns above, different column type.
- **launchd + uvicorn don't hot-reload.** After editing a plist or source you
  must restart; `uvicorn` without `--reload` won't see code changes. But
  `bootout` immediately followed by `bootstrap` is unreliable: the old process
  can still hold port 8765, and the job ends up *loaded but never started*
  (`launchctl print gui/$UID/local.gtd` shows `state = not running`,
  `runs = 0`). Wait for the port to be released, and verify afterwards —
  `launchctl list | grep local.gtd` must show a real PID, not `-`. If it does
  not, `launchctl kickstart -k gui/$UID/local.gtd` starts it.
- **The service's stderr is `~/Library/Logs/gtd/server.error.log`**, not
  `server.err`. Tailing the wrong name looks like a clean startup.

## Testing

```bash
uv run pytest -q
```

Every test gets its own temp SQLite file — no mocks, no shared state, no
monkeypatching of module globals. Add tests for state transitions and route
behavior, not just happy paths. Regression tests should encode the *bug*, not
just the fix (see `test_time_estimate_options_are_sane`).

Before claiming something works, run it. The test suite passing is not the same
as the app working — several bugs here were only visible against a live server.

### Verify the artifact, not the diff

A clean exit code or a passing suite proves the code ran, not that the change
took effect. Inspect the actual OUTPUT for the specific property you changed —
grep it, count it — on the smallest sample that can show it, before trusting a
larger run or a full page load. Learned the expensive way in a sibling project:
a fix shipped twice while the downstream output was provably unchanged, because
"it ran clean" was treated as verification.

### If an LLM call is ever added (see constraint 1 — none exist yet)

Test what the model actually receives, not just the data structure behind it.
A prompt-construction bug can leave the underlying data correct while the
rendered prompt is unchanged. Assert on the literal text the call sends, not on
the object it was built from.

## Conventions

- Comments explain *why*, not *what*. If a line needs a comment to say what it
  does, rewrite the line.
- Docstrings on non-obvious functions; skip them on obvious ones.
- Keep `README.md`, `ADR.md`, and this file current when behavior changes.
- Park proposals and open questions in `HUMAN_PLANS.md` rather than starting
  speculative work.

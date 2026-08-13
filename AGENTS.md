# AGENTS.md — context for AI coding agents

Read this before changing anything. `ADR.md` has the reasoning behind the
decisions below; this file is the operating rules.

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

## Design principles

- **Capture must be frictionless.** `capture()` takes a title and nothing else.
  Metadata is a *clarify*-time concern. Do not add required fields to capture.
- **Every list is a `state` of `items`.** Adding a list means adding an enum
  value, not a table. See ADR-001.
- **Soft delete by default.** `delete_item()` sets `trashed`; hard delete is
  opt-in. Undo should always be possible.
- **Disclose, don't hide.** The tickler withholds deferred items from next
  actions — and the page says how many it is withholding. Silent filtering is a
  bug.
- **Match the method.** This implements David Allen's GTD as specified: the
  clarify decision tree, the two-minute rule, contexts, the four-criteria model
  (context / time / energy / priority). If a change would drift from the method,
  say so explicitly rather than quietly reinterpreting it.

## Layout

```
src/gtd/
├── config.py    env-driven settings; nothing hardcoded to localhost
├── db.py        connection + schema (plain sqlite3, WAL)
├── models.py    ItemState / Energy / ProjectStatus / Source / TIME_ESTIMATES
├── store.py     repository layer — ALL SQL
├── auth.py      argon2id hashing, session key, login rate limiter
├── export.py    markdown export
├── cli.py       argparse entry point
├── web.py       FastAPI app + routes
├── templates/   base, login, index, clarify, list, edit, projects
└── static/      style.css — the entire frontend
```

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
- **`app = create_app()` runs at import.** Importing `gtd.web` creates the
  database file. Harmless (`init_schema` is idempotent) but surprising in tests.
- **launchd + uvicorn don't hot-reload.** After editing a plist or source, you
  must `bootout` then `bootstrap`; `uvicorn` without `--reload` won't see code
  changes.

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

## Conventions

- Comments explain *why*, not *what*. If a line needs a comment to say what it
  does, rewrite the line.
- Docstrings on non-obvious functions; skip them on obvious ones.
- Keep `README.md`, `ADR.md`, and this file current when behavior changes.
- Park proposals and open questions in `HUMAN_PLANS.md` rather than starting
  speculative work.

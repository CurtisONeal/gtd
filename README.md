# GTD

A self-hosted Getting Things Done system. Python, SQLite, server-rendered HTML.
Your data stays on your machine.

## Why this exists

Built after reviewing a GTD app that stored everything in Google Sheets on a personal Drive account. The method it implemented was sound; the substrate wasn't. This one keeps the method and fixes the foundation:

- **Self-hosted** — SQLite file on your own machine, no third-party data store
- **Real auth** — argon2id password hashing, signed session cookies, login rate limiting
- **Reproducible build** — `uv` with a lockfile
- **Deterministic** — no LLM anywhere in the core. Model calls belong where judgment is needed (coaching, weekly review), not for moving a row between lists
-
- **No JavaScript dependencies** — zero. Plain forms, POST-redirect-GET. Works with JS disabled, back button behaves, refresh never double-submits

## Getting started

```bash
cd ~/dev/gtd

# 1. Create the database and seed default contexts/areas
uv run gtd init-db

# 2. Set your login (you choose the password; only its hash is stored)
uv run gtd set-password

# 3. Run it
uv run uvicorn gtd.web:app --port 8765
```

Then open <http://localhost:8765>.

`.env` is created from `.env.example` and is gitignored. Generate a session
secret with `uv run gtd gen-secret`.

## The design decision that matters

Every GTD list — inbox, next actions, waiting-for, someday/maybe, reference — is
a **`state` of one `items` table**, not a separate table. GTD items move between
lists constantly, so a move is a single-column `UPDATE`: no copy-and-delete
across tables, no archive to keep in sync, no drift. Completing and
un-completing are symmetric one-liners.

That also makes the lists most GTD apps skip nearly free, plus one they usually
lack entirely: `defer_until`, a real tickler. Deferred items *disappear* from
next actions until their date arrives, and the list tells you how many are
hidden so it's never silent.

## The clarify flow

Inbox processing walks Allen's actual decision tree, one question per page:

```
Is it actionable?
├─ No  → Reference · Someday/Maybe · Trash
└─ Yes → Can it be done in one step?
         ├─ No  → Project (+ desired outcome, + first next action)
         └─ Yes → Under two minutes?
                  ├─ Yes → do it now, mark done
                  ├─ Defer   → context, energy, time, priority, due, defer-until
                  └─ Delegate → who you're waiting on
```

Items are processed oldest-first so nothing rots at the bottom. "Skip for now"
sends one to the back of the queue rather than letting you cherry-pick forever.

## CLI

```bash
uv run gtd init-db          # create database, seed defaults
uv run gtd set-password     # create or change the login
uv run gtd capture "..."    # capture straight to the inbox
uv run gtd status           # counts per list, stalled project count
uv run gtd export           # write markdown copies of every list
uv run gtd gen-secret       # print a session secret for .env
```

## Markdown export

SQLite is the source of truth; `uv run gtd export` mirrors every list to
readable, greppable, git-versionable markdown in `exports/`. Useful for reading
at a terminal, diffing week over week, or handing a list to something else
without it needing to speak SQLite.

## Layout

```
src/gtd/
├── config.py    env-driven settings — nothing hardcoded to localhost
├── db.py        connection + schema (plain sqlite3, WAL, no ORM)
├── models.py    ItemState / Energy / ProjectStatus / Source enums
├── store.py     repository layer — ALL SQL lives here
├── auth.py      argon2id hashing, session helpers, login rate limiter
├── export.py    markdown export
├── cli.py       command line entry point
├── web.py       FastAPI app and routes
├── templates/   Jinja2 — base, login, index, clarify, list, projects
└── static/      style.css (that's the entire frontend)
```

Confining SQL to `store.py` is what makes a later move to Postgres a real
option rather than a rewrite.

## Tests

```bash
uv run pytest -q
```

81 tests covering the store, state transitions, the tickler, auth, rate
limiting, markdown export, and every web route including the full clarify tree.
Each test gets its own temp SQLite file — no mocks, no shared state.

## Deployment phases

1. **Local** (now) — localhost only, plain http, `GTD_SECURE_COOKIES=false`
2. **Tailscale** — reachable from phone/iPad without exposing anything publicly
3. **TLS** (optional) — nginx or Caddy in front; set `GTD_SECURE_COOKIES=true`

Nothing in the code assumes localhost, so moving between phases is a `.env`
change.

## Capture from elsewhere

`POST /api/capture` accepts `{"title": "...", "notes": "...", "source": "..."}`
with a `Authorization: Bearer <GTD_CAPTURE_TOKEN>` header. Disabled unless
`GTD_CAPTURE_TOKEN` is set. Intended for a Discord bot, an email poller, or a
phone shortcut — so capture never depends on opening the web UI.

## Security notes

- Passwords: argon2id, 12 character minimum, never logged
- Sessions: signed cookies, `HttpOnly`, `SameSite=Lax` (which is also the CSRF
  defense — cross-site POSTs don't carry the cookie)
- Login: 5 attempts per 15 minutes per IP; identical error whether or not the
  username exists
- Redirects: only ever to local paths, never to a supplied host
- `.env` and `*.db` are gitignored

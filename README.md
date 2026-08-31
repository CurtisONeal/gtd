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
sΩ`

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

Waiting For also handles blocked work. Use **Waiting on** for people or
external events, and **Blocked by task** for task dependencies such as
`Buy cookies -> Eat cookies`. When the blocking task is completed, the blocked
item automatically returns to Next Actions. Free-text `waiting_on` notes do not
auto-unblock; only the real dependency link does.

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

**Two other ways in.** Capture-then-clarify is the discipline, but it isn't the
only route: each of Next Actions, Waiting For, Someday and Reference has an
"Add directly to…" form for when you already know where something belongs, and
the edit page can move any item to any list. Done and Trash have no add form —
they are outcomes, not destinations.

## Books

`/books` is an *ordered* list rather than an actionable one. Books are grouped
by category — fiction, graphic novels, general non-fiction, technology — and
ranked within each, independently. Each book carries whether it's started (and
roughly when), a bucketed percentage, and whether it's an audiobook.

Three things are deliberate:

- **Books never generate next actions.** If a book needs one ("finish ch. 3"),
  capture it as an ordinary task. There is no project linkage and no dependency
  machinery.
- **Progress is a bucket** (0 / 25 / 33 / 50 / 66 / 75 / 100), not a free
  number. It's an estimate; a text box would only invite fiddling.
- **Floating a category to the top is transient.** It's a "work on this shelf
  now" view, not a stored preference — nothing about it persists.

Finishing a book completes it like anything else, so it leaves the page rather
than sitting at 100%. See ADR-012.

## Checklists

`/checklists` holds sets you *run* rather than tasks you do — what to take to
the dojo, what to consider when building a Magic deck. Items are ordered within
their list, and each list is one of two kinds:

- **Evergreen** — run repeatedly. **Reset** clears every tick and leaves the
  items, their order and the list itself alone. It never completes.
- **One-off** — "build the shelves". It finishes once and leaves the index.
  Ticking everything does *not* complete it; the page says so and waits for you.

Ticking is checklist-local and is **not** the Done state. If a tick moved an
item to Done, reset would have to pull rows back out of Done, and packing a bag
would litter the Done list every time.

## Technology projects

`/tech` is a re-orderable dump list and nothing more — no outcome, no area, no
review date. It exists so a "might build this someday" idea has somewhere to sit
without earning project ceremony. If one grows into real work, capture it as a
project. See ADR-013 for why this and one-off checklists are both accepted
overlaps with projects.

## CLI

```bash
uv run gtd init-db          # create database, seed defaults
uv run gtd set-password     # create or change the login
uv run gtd capture "..."    # capture straight to the inbox
uv run gtd status           # counts per list, stalled project count
uv run gtd export           # write markdown copies of every list
uv run gtd serve            # run the web server (honours GTD_LOCAL_ONLY)
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
├── models.py    ItemState / Energy / ProjectStatus / Source, TIME_ESTIMATES
├── store.py     repository layer — ALL SQL lives here
├── auth.py      argon2id hashing, session helpers, login rate limiter
├── export.py    markdown export
├── cli.py       command line entry point
├── web.py       FastAPI app and routes
├── templates/   Jinja2 — base, login, index, clarify, list, edit, projects
└── static/      style.css (that's the entire frontend)
```

Confining SQL to `store.py` is what makes a later move to Postgres a real
option rather than a rewrite.

## Tests

```bash
uv run pytest -q
```

The tests cover the store, state transitions, dependencies, the tickler, auth,
rate limiting, markdown export, editing and undo, and every web route including
the full clarify tree. Each test gets its own temp SQLite file — no mocks, no
shared state.

## Running it as a service

`uv run uvicorn ...` in a terminal dies when that terminal closes. To keep it up
across logout and reboot, run it under a supervisor.

**macOS (launchd).** Create `~/Library/LaunchAgents/local.gtd.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>local.gtd</string>
    <key>ProgramArguments</key>
    <array>
        <string>/ABSOLUTE/PATH/TO/gtd/.venv/bin/uvicorn</string>
        <string>gtd.web:app</string>
        <string>--host</string><string>127.0.0.1</string>
        <string>--port</string><string>8765</string>
    </array>
    <key>WorkingDirectory</key><string>/ABSOLUTE/PATH/TO/gtd</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>/tmp/gtd.log</string>
    <key>StandardErrorPath</key><string>/tmp/gtd.error.log</string>
</dict>
</plist>
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.gtd.plist
launchctl list local.gtd          # confirm: PID set, LastExitStatus 0

# stop / restart
launchctl bootout   gui/$(id -u) ~/Library/LaunchAgents/local.gtd.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.gtd.plist
```

**Linux (systemd user unit)** is the same shape: `ExecStart` pointing at
`.venv/bin/uvicorn`, `WorkingDirectory` at the repo, `Restart=always`.

**Note:** launchd does not re-read a changed plist automatically, and `uvicorn`
without `--reload` does not pick up code changes. After editing either, bootout
and bootstrap again.

## Remote access

### Phase 1 — local only (default)

`--host 127.0.0.1`, plain http, `GTD_SECURE_COOKIES=false`. Nothing outside the
machine can reach it.

### Phase 2 — Tailscale (recommended)

A private WireGuard network between your own devices. Nothing is exposed to the
public internet, and traffic is encrypted at the network layer.

```bash
brew install tailscale                  # macOS
sudo brew services start tailscale      # starts the daemon (needs sudo)
tailscale up                            # prints an auth URL — sign in
tailscale ip -4                         # your machine's 100.x.y.z address
```

Install Tailscale on your phone/iPad and sign in with the **same account**, then
browse to `http://<100.x.y.z>:8765`.

The server must listen on an interface Tailscale can reach — `127.0.0.1` is not
one. Two options in the plist:

| `--host` | Reachable from | Trade-off |
|---|---|---|
| `0.0.0.0` | Tailscale **and** local LAN | Simplest. Anyone on your LAN can reach the login page. |
| `100.x.y.z` | Tailscale only | Tighter. Breaks if the tailnet address ever changes. |

Keep `GTD_SECURE_COOKIES=false` on this phase. Tailscale encrypts at the
WireGuard layer, but the connection is still plain `http` from the browser's
point of view — setting the Secure flag would stop the cookie being sent at all
and lock you out.

### Work machines — local only, always

**A work deployment gets none of this.** No Tailscale, no remote access, no
inbound network exposure of any kind, ever. It runs on `127.0.0.1` on that
machine and is reachable only from that machine.

This is not a default to be relaxed later — it is the deployment mode for work
instances. Keep `--host 127.0.0.1`, do not install Tailscale, and do not put a
tunnel or reverse proxy in front of it. A work instance's data stays on the work
machine and never traverses a personal network.

Practically: clone the repo, `uv run gtd init-db`, `uv run gtd set-password`,
then set **`GTD_LOCAL_ONLY=true`** in `.env` and run `uv run gtd serve`.
Separate `.env`, separate `GTD_DB_PATH`, no shared state with any personal
instance.

`GTD_LOCAL_ONLY` is enforced, not advisory, in two independent places:

1. `gtd serve` refuses to bind anything but loopback and exits non-zero.
2. The app rejects any request whose peer address isn't on this machine, with
   `403`, before session parsing or auth. This holds even if someone bypasses
   `gtd serve` and runs `uvicorn --host 0.0.0.0` directly — verified by test and
   against a real remote connection.

The peer address comes from the socket, never from a forwarded header, so it
can't be spoofed by a client.

### Phase 3 — TLS (optional)

Either `tailscale serve` (gives a real cert on a `*.ts.net` name, no ports or
reverse proxy to manage), or nginx/Caddy in front. **Then**, and only then, set
`GTD_SECURE_COOKIES=true`.

Nothing in the code assumes localhost, so moving between phases is a `.env` and
a `--host` change.

## Capture from elsewhere

`POST /api/capture` accepts `{"title": "...", "notes": "...", "source": "..."}`
with a `Authorization: Bearer <GTD_CAPTURE_TOKEN>` header. Disabled unless
`GTD_CAPTURE_TOKEN` is set — **it is empty today, so this endpoint 404s**.
Intended for a Discord bot, an email poller, or a phone shortcut — so capture
never depends on opening the web UI.

**This is the only JSON endpoint, and it is WRITE-ONLY.** There is no read API:
every read route returns HTML behind session auth. An agent that needs to
*read* GTD (a briefing, a review, a report) should run `gtd export` and read the
markdown — see `Daily_Briefing_Agent.md`.

The planned Discord integration lives outside this repo in
`/Users/s_admin/Documents/agent_set_up/direct_scripts_bot`. That bot currently
handles deterministic reminder/todo slash commands; it does not yet call GTD's
capture API. The integration boundary is intentionally small: the bot should
send a JSON request to this endpoint, and this app should not import or depend
on `agent_set_up` code.

Keep the secrets separate. `DISCORD_BOT_TOKEN` belongs in the bot project's
local `.env`; `GTD_CAPTURE_TOKEN` belongs in this repo's local `.env`. Neither
secret belongs in Git.

## Project docs

| File | What's in it |
|---|---|
| `ADR.md` | Architecture decisions and why — read before changing the data model |
| `AGENTS.md` | Operating rules and known gotchas, aimed at AI coding agents |
| `FIXED_BUGS.md` | Concrete bugs fixed, symptoms, causes, and regression tests |
| `GTD_METHOD.md` | David Allen GTD method context and how the app maps to it |
| `HUMAN_PLANS.md` | Scratchpad for ideas, open questions, and what's next |
| `Daily_Briefing_Agent.md` | **Read this before wiring any agent to GTD data** — there is no read API; use `gtd export` |

## Security notes

- Passwords: argon2id, 12 character minimum, never logged
- Sessions: signed cookies, `HttpOnly`, `SameSite=Lax` (which is also the CSRF
  defense — cross-site POSTs don't carry the cookie)
- Login: 5 attempts per 15 minutes per IP; identical error whether or not the
  username exists
- Redirects: only ever to local paths, never to a supplied host
- `.env` and `*.db` are gitignored

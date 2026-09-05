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

The same trick carries the lists that are *not* actionable at all — books,
checklists and technology projects. They are states of the same table with a
`rank` for sequence, so they reach the same editing and undo machinery without
being a second system. None of them generate next actions.

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

## Recurring tasks

Any next action can repeat. Set it on the edit page, two ways:

- **Every N days / weeks / months / years** — "change the furnace filter every
  3 months".
- **On chosen days** — any combination of the seven days. Garbage day is a
  Wednesday; a stand-up is Mon–Fri. The whole week reads back as "every day",
  Mon–Fri as "every weekday", Sat+Sun as "every weekend".

Intervals also choose what the clock runs from. **The schedule** keeps the
cadence: due Monday, finished Wednesday, a weekly task returns the following
Monday. **Completion** restarts it: water the plants five days after you last
actually watered them.

Completing a repeating task files it under Done and creates the next
occurrence, deferred to its date. Two consequences worth knowing:

- **Done accumulates history.** A daily task leaves a row a day. That is
  deliberate — it is how you can tell you have done something two hundred times.
- **Missed occurrences are never backfilled.** Three days late on a daily task
  produces one next occurrence, not three.

It rides the existing tickler rather than adding a scheduler: the next
occurrence is an ordinary Next Action with `defer_until` set, hidden until its
date, with the count of hidden items disclosed as usual. Month-ends clamp — 31
January plus a month is 28 February, not 3 March, so a monthly task cannot drift
later every time it repeats. See ADR-015.

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
uv run gtd backup           # verified snapshot, copied offsite, old ones pruned
uv run gtd backups          # list snapshots, checking each is readable
uv run gtd restore <snap>   # replace the database from a snapshot
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
├── db.py        connection + schema + migrations (plain sqlite3, WAL, no ORM)
├── models.py    ItemState / Energy / ProjectStatus / ChecklistStatus /
│                BookCategory / Source, TIME_ESTIMATES, PERCENT_BUCKETS
├── store.py     repository layer — ALL SQL lives here
├── auth.py      argon2id hashing, session helpers, login rate limiter
├── export.py    markdown export
├── cli.py       command line entry point
├── web.py       FastAPI app and routes
├── templates/   Jinja2 — base, login, index, clarify, list, edit, projects,
│                books, checklists, checklist, tech
└── static/      style.css (that's the entire frontend)
```

Confining SQL to `store.py` is what makes a later move to Postgres a real
option rather than a rewrite.

Schema changes are versioned: `SCHEMA` describes the current shape for a fresh
database, and `MIGRATIONS` brings an existing one up to it. Both are needed —
`CREATE TABLE IF NOT EXISTS` cannot add a column to a table that already exists.

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

## Setting up backups

Backups have two layers. The first is enough on its own; the second covers
losing the building.

### 1. A second machine (do this first)

Snapshots go to another machine you own. Either a mounted share or SSH:

```bash
# a share already mounted on this machine — no SSH, no keys
GTD_BACKUP_REMOTE=/Volumes/some_drive/gtd-backup

# or over SSH to a host on the tailnet
GTD_BACKUP_REMOTE=user@100.x.y.z:/path/on/that/machine/gtd-backups/
GTD_BACKUP_IDENTITY=~/.ssh/gtd_backup
```

For the SSH form, the key has to be authorised on the *far* machine, which
needs that machine's password — so run it yourself:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/gtd_backup -N "" -C "gtd-backup"
ssh-copy-id -i ~/.ssh/gtd_backup.pub user@100.x.y.z
ssh -i ~/.ssh/gtd_backup -o BatchMode=yes user@100.x.y.z whoami   # must print the user
```

`ssh-copy-id` needs **Remote Login** enabled on the far Mac
(System Settings → General → Sharing → Remote Login). File Sharing is a
different service and does not enable SSH.

Then load the timer, which runs daily at 03:15:

```bash
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/local.gtd-backup.plist
launchctl kickstart gui/$UID/local.gtd-backup     # bootstrap often loads without starting
launchctl print gui/$UID/local.gtd-backup | grep -E "state =|runs ="
```

### 2. An encrypted copy off-site (optional)

Only this layer needs encryption, because it is the only one a third party
holds. Requires `brew install age rclone`.

```bash
# one keypair, once
age-keygen -o ~/.config/gtd/age-identity.txt
chmod 600 ~/.config/gtd/age-identity.txt
grep "public key" ~/.config/gtd/age-identity.txt      # this is the recipient
```

Configure a cloud remote. This is interactive and opens a browser to authorise:

```bash
rclone config
#  n) New remote
#  name> gdrive
#  Storage> drive          (pick your provider from the list)
#  client_id / client_secret> leave blank for the defaults
#  scope> 1                (full access) or 3 (drive.file — only files rclone creates)
#  Edit advanced config> n
#  Use web browser to automatically authenticate> y
#  Configure this as a Shared Drive> n
#  y) Yes this is OK  ->  q) Quit config
rclone lsd gdrive:                                    # should list your Drive folders
rclone mkdir gdrive:gtd-backups
```

Then in `.env`:

```bash
GTD_BACKUP_CLOUD=gdrive:gtd-backups
GTD_BACKUP_AGE_RECIPIENT=age1...        # the PUBLIC key
GTD_BACKUP_AGE_IDENTITY=~/.config/gtd/age-identity.txt
```

**Keep the identity file somewhere that is not this machine.** It is three
lines — a created date, the public key, and a line beginning `AGE-SECRET-KEY-1`.
That last line is the whole ballgame: without it every encrypted backup is
unreadable noise. A password manager secure note is fine; so is paper. Do not
put it in the bucket it decrypts, and do not commit it.

Encrypting needs only the public key, so this machine can produce cloud backups
it cannot itself read. If the cloud remote is set but the recipient is not,
`gtd backup` exits non-zero rather than uploading plaintext.

## Backups

The database is the point, and `exports/` is markdown — lossy, and not a restore
path. `gtd backup` is.

```bash
uv run gtd backup                    # snapshot, verify, copy offsite, prune
uv run gtd backup --verify-restore   # also rehearse a restore into a scratch copy
uv run gtd backups                   # list snapshots, checking each is readable
uv run gtd restore <snapshot> --yes  # replace the database (stop the server first)
```

**A snapshot is not a file copy.** The database runs in WAL mode, so committed
data can be sitting in the `-wal` sidecar. Copying just the `.db` can produce a
file that is not merely stale but unusable — in a direct test, a naive `cp` of a
WAL-mode database yielded `no such table`, because even the schema was still in
the log. `gtd backup` uses SQLite's `VACUUM INTO`, which is safe while the
server is running. The same caveat applies to Time Machine and any other
file-level backup: useful, but not a guarantee for an open SQLite database.

**Every snapshot is verified as it is written** — integrity-checked and opened
to confirm it is a GTD database, not just valid SQLite. A snapshot that fails is
deleted rather than left looking like protection. `restore` re-checks before
overwriting anything, and moves the replaced database aside as `*.replaced-*`.

Configure the offsite copy in `.env` (see `.env.example`). Two forms:

```bash
# a mounted share on another machine — no SSH needed
GTD_BACKUP_REMOTE=/Volumes/some_drive/gtd-backup

# or over SSH
GTD_BACKUP_REMOTE=user@100.x.y.z:/Users/user/gtd-backups/
GTD_BACKUP_IDENTITY=~/.ssh/gtd_backup
GTD_BACKUP_KEEP=14
```

A directory destination is **refused if it sits on the same device as the
database**. That is not pedantry: when a network share unmounts, macOS leaves an
empty directory at the same path on the boot disk, and without the check every
backup would keep reporting success while landing on the machine it is supposed
to outlive.

The target is another machine on the tailnet — hardware you own, encrypted
transport, no third party. That is a deliberate reading of "nothing leaves the
machine": the constraint exists so nobody else holds your data, and a second
machine of your own does not break it. Sending snapshots to a cloud provider
would, unless they are encrypted first. See ADR-014.

`local.gtd-backup.plist` runs it daily at 03:15, and at load, so a machine that
was asleep still catches up.

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

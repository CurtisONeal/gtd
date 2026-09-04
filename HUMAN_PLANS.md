# HUMAN_PLANS.md

Scratchpad for edits, ideas, and open questions. Park things here instead of
starting speculative work or losing them in chat history.

**How to use this:** add to *Inbox* freely — it's a capture surface, same idea as
the app. Things graduate to *Next up* once decided. Move to *Done* with a date so
the reasoning stays findable. Anything with a real architectural consequence
should end up in `ADR.md` when it lands.

---

## Inbox — unsorted, undecided

- **Tailnet-only binding.** The personal instance listens on `0.0.0.0`, so it's
  reachable from the home LAN as well as the tailnet; the login is the only gate
  there. `GTD_LOCAL_ONLY` does *not* cover this — it means *this machine only*,
  and treats a tailnet address as remote. What's wanted is a third mode:
  loopback + tailnet, LAN excluded. Either bind `100.x.y.z` directly (brittle if
  the address changes) or extend the guard to accept the `100.64.0.0/10` CGNAT
  range Tailscale uses. The latter is probably right and reuses `_is_loopback`'s
  shape.
- `tailscale serve` for real TLS on the `*.ts.net` name, which would then allow
  `GTD_SECURE_COOKIES=true`. May also solve the item above for free.
- Someday/Maybe review cadence — items go in and currently nothing brings them
  back out. Overlaps with Weekly Review.
- Keyboard shortcuts for the clarify flow (y/n and 1/2/3 on the decision steps).
  Would speed up inbox processing a lot, but see AGENTS.md constraint 2 — needs
  thought about whether it can be done without a JS dependency. (`accesskey`
  attributes might get most of the way with zero JS.)
- Recurring items. Deliberately absent so far; GTD proper handles these with a
  tickler, which `defer_until` already provides. Decide whether true recurrence
  is wanted or whether the tickler is sufficient.
- Full-text search across all lists.
- Bulk operations (select several inbox items, file them all as reference).
- Now that there are collaborators: decide whether to add CI (a GitHub Action
  running `pytest`) before accepting outside changes, and whether `main` should
  take direct pushes or require PRs.

## Next up — decided, not built

- **Backup and restore.** Raised 2026-08-30, once the app became something to
  depend on. **There is no backup today**, of GTD or of this machine: `tmutil`
  reports no Time Machine destination configured. `exports/` is markdown and
  lossy — it is a reading format, not a restore path.

  Three things are true regardless of where backups go:

  - **A copy must not be `cp gtd.db`.** The database is in WAL mode, so a plain
    file copy can miss committed pages sitting in `-wal`. Use SQLite's own
    `.backup` / `VACUUM INTO`, which is what the ad-hoc backups taken during the
    Books work already used.
  - **A restore has to be rehearsed, not assumed.** Restoring into a scratch
    path and starting the app against it is the only thing that proves a backup
    is real. Verify the artifact, not the procedure.
  - **`.env` is part of a full restore** and is a secret. It never goes offsite
    unencrypted, and never into this repo.

  **The decision that needs making: where the offsite copy lives.** This is the
  one place backup meets AGENTS.md constraint 4 ("nothing leaves the machine"),
  so it needs an explicit decision and an ADR rather than being assumed.

  | Option | Constraint 4 | Notes |
  |---|---|---|
  | **Second Mac over Tailscale** (`curtiss-mac-mini`) | Honours the intent — hardware Curtis owns, encrypted transport, no third party | Recommended. Needs the other machine to be up sometimes; that is the only real weakness |
  | Encrypted blob to iCloud/B2/S3 | Third party holds ciphertext only | Survives losing both machines. Adds a key to manage, which becomes the new single point of failure |
  | Time Machine to a local disk | Local only | Worth doing anyway for the whole machine, but a `.db` in WAL mode is not guaranteed consistent in a file-level backup |

  These are not exclusive: the second Mac for routine recovery plus an encrypted
  offsite copy for disaster is the belt-and-braces version.

  **Built 2026-08-30 — local half only.** `gtd backup` / `gtd backups` /
  `gtd restore` exist and are tested; the first real snapshot is taken. See
  ADR-014.

  **Parked, waiting on Curtis — one step.** The offsite copy is not running.
  A dedicated key exists at `~/.ssh/gtd_backup`, but it has not been authorised
  on `curtiss-mac-mini` (100.102.123.60), which needs that machine's password:

  ```
  ssh-copy-id -i ~/.ssh/gtd_backup.pub USER@100.102.123.60
  ```

  Then: set `GTD_BACKUP_REMOTE=USER@100.102.123.60:/Users/USER/gtd-backups/`
  and `GTD_BACKUP_IDENTITY=~/.ssh/gtd_backup` in `.env`, run a real backup
  across the tailnet, rehearse a restore, and only then load
  `~/Library/LaunchAgents/local.gtd-backup.plist` (written, deliberately not
  loaded — a timer that silently ships nothing is worse than no timer).

  **Until that is done there is exactly one copy of the data, on one machine.**

  Still open, later phases: an encrypted cloud copy for disaster recovery, and
  Time Machine for the machine as a whole — noting a file-level backup does not
  guarantee a consistent WAL-mode database, so it complements `gtd backup`
  rather than replacing it.

- **Weekly Review flow.** Build a guided server-rendered weekly review feature.
  This is the biggest gap versus the method as written: Allen calls weekly
  review the critical success factor, and this app currently has no review flow.

  Next action:
  - Design the `/review/weekly` route and page sequence using the existing
    no-JS, POST-redirect-GET UI style.

  Expected review surfaces:
  - Inbox-to-zero check.
  - Active projects with no open next action or waiting item.
  - Waiting For items older than a configurable/reasonable age.
  - Someday/Maybe items to reconsider.
  - Deferred/tickler items becoming current.
  - A final checklist confirming the system is current enough to trust.

- **Discord capture.** Goal: `/capture <text>` in Discord sends the text to this
  GTD instance through `POST /api/capture`, so phone capture does not require
  opening the web UI.

  Current known state:
  - GTD already has `POST /api/capture`.
  - The API is disabled until `GTD_CAPTURE_TOKEN` is set.
  - `direct_scripts_bot` code exists at
    `/Users/s_admin/Documents/agent_set_up/direct_scripts_bot`.
  - The bot currently has deterministic slash commands for reminders and todos:
    `/add remind`, `/add todo`, `/list remind`, and `/read todos`.
  - The bot does not yet implement a GTD `/capture` slash command and does not
    call GTD's `POST /api/capture`.
  - The bot has `.env.example`, but no local `.env` was present during the
    2026-08-28 check.
  - The launchd plist exists at
    `~/Library/LaunchAgents/local.directscriptsbot.plist`, but
    `local.directscriptsbot` was not loaded during the 2026-08-28 check.
  - We do not know from local files whether a Discord application for
    `direct_scripts_bot` already exists. Curtis must check the Discord
    Developer Portal.
  - `agent_set_up` does include Discord context-reset tooling:
    `scripts/agent/clear_discord_session.sh`, wired to the plain-text Hermes
    verbs `clear tokens` / `clear session`. That is separate from
    `direct_scripts_bot`; the slash-command equivalent is only planned.

  Human next action:
  - In Discord Developer Portal, confirm whether the Discord application for
    `direct_scripts_bot` exists. If it does not, create it. Then create/reset the
    Discord bot token and keep it out of Git.

  Future code action, only with explicit authorization:
  - Add a GTD capture slash command to the existing `direct_scripts_bot` code,
    then wire its environment to `GTD_CAPTURE_TOKEN` and the GTD capture URL.

  Confirm or create the Discord application:
  - Open `https://discord.com/developers/applications`.
  - Look for an existing application named `direct_scripts_bot`.
  - If absent, choose New Application, name it `direct_scripts_bot`, accept the
    developer terms, and create it.
  - Open the app's Bot page. Newly created Discord apps normally have a bot user;
    if the UI offers Add Bot instead, add one.
  - Prefer a slash command implementation for `/capture <text>`. That should use
    `applications.commands`; do not enable privileged Message Content intent
    unless the bot code explicitly reads ordinary message text.
  - Install/invite the app to the intended Discord server with the least
    permissions needed. For a slash-command-only capture bot, start with
    `applications.commands`; add `bot` and Send Messages only if the bot needs to
    post channel replies.

  Create the Discord bot token:
  - In the Discord Developer Portal, open `direct_scripts_bot`.
  - Go to Bot -> Token.
  - Use Reset Token to generate a token, then copy it immediately.
  - Store it in a password manager or the separate bot project's local `.env` as
    `DISCORD_BOT_TOKEN=...`.
  - Never paste the Discord bot token into this repo, Discord chat, docs, or Git.
    If it leaks, reset it in the Developer Portal.

  Set `GTD_CAPTURE_TOKEN` on the GTD server:
  - Generate a separate GTD shared secret. Do not reuse the Discord bot token.
    Example: `python -c 'import secrets; print(secrets.token_urlsafe(32))'`.
  - Add it to `/Users/s_admin/dev/gtd/.env` as `GTD_CAPTURE_TOKEN=<generated>`.
    The `.env` file is local-only and must stay uncommitted.
  - Restart the launchd service so `gtd.web:app` reloads `.env`:
    `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/local.gtd.plist`
    then
    `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.gtd.plist`.
  - Configure the Discord bot process with the same `GTD_CAPTURE_TOKEN` and the
    capture URL. If the bot runs on this Mac, use
    `http://127.0.0.1:8765/api/capture`; if it runs from another tailnet device,
    use `http://octobobs-mac-mini.tail7ccdf0.ts.net:8765/api/capture`.
  - The bot should call GTD with:
    `Authorization: Bearer <GTD_CAPTURE_TOKEN>` and JSON
    `{"title": "<captured text>", "source": "discord"}`.
  - Smoke test by capturing a real disposable item, then delete or clarify it in
    GTD.

## Done

- 2026-08-12 — Initial build: capture, full clarify tree, all GTD lists,
  projects, auth, markdown export, 81 tests.
- 2026-08-13 — Time estimates fixed (were 1, 6, 11, 16 — a `min`/`step`
  interaction). See ADR-005.
- 2026-08-13 — Editing and undo added after both were found missing in real
  use. See ADR-006.
- 2026-08-13 — launchd service so the server survives terminal close and
  reboot; Tailscale for remote access. See ADR-007.
- 2026-08-14 — **Direct-add to lists.** Waiting For, Someday and Reference had
  no route in except processing an inbox item — impossible at inbox zero.
  Each addable list now has its own add form. See ADR-009.
- 2026-08-14 — **Work instances are local-only, permanently**, and that is now
  enforced in code rather than documented in prose: `gtd serve` refuses a
  non-loopback bind, and an outermost middleware rejects non-loopback peers with
  403 even if someone runs `uvicorn --host 0.0.0.0` directly. Off by default so
  the personal tailnet instance is unaffected. See ADR-008 and ADR-010.
- 2026-08-14 — **Repo made public** (`CurtisONeal/gtd`), after auditing every
  commit — not just the working tree — for `.env`, `*.db`, and the live session
  secret. All absent. Collaborators invited with write access: `ecodad`
  (Jonathan Hunt), `drjat42` (Josh Tauber), `xdg` (David Golden), `benton`
  (Benton Roberts).
- 2026-08-24 — **First-class task dependencies.** Blocked work now lives in
  Waiting For with a real prerequisite link instead of title text. Completing
  the prerequisite promotes newly unblocked work back to Next Actions. See
  ADR-011 and `FIXED_BUGS.md`.
- 2026-08-28 — **Phone joined the tailnet.** The phone can reach the personal
  GTD instance through Tailscale at
  `http://octobobs-mac-mini.tail7ccdf0.ts.net:8765`.
- 2026-08-30 — **Ordered lists (commit 1) and Books (commit 2).** `items.rank`
  as sequence within a group, and `/books` grouped by category with progress
  buckets. See ADR-012. Two things the spec had not anticipated and which are
  now fixed: schema bumps were silent no-ops (there was no migration mechanism
  at all), and running the test suite from the repo root mutated the live
  database, because importing `gtd.web` runs `create_app()` and `GTD_DB_PATH`
  defaults to `./gtd.db`.
- 2026-08-30 — **Checklists and Technology Projects (commit 3).** Checklists got
  a container table for `evergreen` and one-off completion; evergreen lists
  reset, one-offs complete manually, and `ticked` is never the `done` state.
  Technology projects are the ordered-list concept with nothing added. See
  ADR-013. Fixed a migration ordering bug found on the way: indexes were applied
  with the tables, before the migration that added the column they covered,
  which would have crashed startup on any existing database.
  **The whole ordered lists + Books + Checklists spec is now built.**

---

## Read API for agents — scoped, not built

**Not needed for the daily brief.** That runs on Octobob with
`requires_local_device: true`, so it uses `gtd export` and reads the markdown —
no HTTP, no token, no new surface. See `Daily_Briefing_Agent.md`.

This is only worth building if something must read GTD from a machine that is
**not** this one.

**Effort: 1-2 sessions.** Not a small addition — the current app has *no* read
API at all. `POST /api/capture` is the only JSON endpoint and it is write-only;
every read route returns HTML behind session-cookie auth.

What it would actually take:

| Piece | Notes |
|---|---|
| `GET /api/items?state=…` | serialisation, filtering, pagination decisions |
| `GET /api/projects` | project status + linked actions |
| Token auth for reads | reuse the capture-token pattern, or a separate read token |
| Respect `GTD_LOCAL_ONLY` | ADR-010 — the guard must not be weakened for convenience |
| Tests | route behaviour, auth rejection, and the local-only guard specifically |
| README + AGENTS updates | the API section currently documents capture only |

**One decision to make first:** whether a read token is the same secret as
`GTD_CAPTURE_TOKEN` or a separate one. They are different privileges — read
exposes everything, capture only adds an inbox item — and collapsing them means
anything that can capture can also read the whole system.

**Note:** `GTD_CAPTURE_TOKEN` exists as an empty line in `.env` today. The
endpoint is 404 until it has a value. A previous session believed it was
configured; it is not.

## Open questions

- **Does the two-minute rule actually get used?** It's implemented as a clarify
  step, but if in practice everything gets deferred, the step is friction. Worth
  watching before adding anything else to that flow.
- **Now that lists are directly addable, does the clarify flow still get used?**
  ADR-009 traded some GTD orthodoxy for usability. If capture-then-clarify falls
  into disuse and everything gets filed directly, that's worth noticing — it
  would mean the inbox has stopped being the single front door, which is most of
  what makes the method work.
- **Are areas of focus and projects both earning their keep,** or is one enough
  at this scale?
- **Horizons above areas of focus** (goals, vision, purpose — Allen's H3–H5) are
  entirely absent. Deliberate for now: they're review artifacts more than daily
  ones. Revisit if the Weekly Review flow gets built.
- ~~Is `benton` the right Benton Roberts?~~ **Resolved 2026-08-14:** yes,
  confirmed by Curtis. The `bentonroberts.com` / Elevate Services listing rather
  than pannix.com is fine. Invited for visibility; unlikely to actively
  contribute.

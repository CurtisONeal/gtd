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
  defaults to `./gtd.db`. Commit 3 (Checklists + Technology Projects) is the
  remaining piece.

---

## Ordered lists + Books — specced, decided, not built

Decided 2026-08-30. **All the open questions below are answered** — this is
ready to build in a fresh session. Sequence it as three commits.

### The shape underneath

Books, Checklists and "Technology Projects" are the same thing: an **ordered,
categorised, low-ceremony list that sits outside the actionable flow**. Books
just adds progress fields. Build the shared concept once, specialise it.

### Commit 1 — ordered lists

**Decision: option A.** New `ItemState` value(s) plus nullable columns on
`items`. Not a separate table.

Rationale: keeps ADR-001 intact ("adding a list means adding an enum value"),
keeps these items inside the one system, and a few nullable columns is a
smaller cost than a parallel world that cannot reach contexts, dependencies or
the clarify flow. Record this in ADR.md when built.

What "ordered" needs that items lack: a **rank within a category**, distinct
from `priority` (which is P1-P3 importance, not sequence).

### Commit 2 — Books, specialising the above

**Fields:**

| Field | Notes |
|---|---|
| `book_category` | **new concept, not `areas`** — fiction / graphic novel / general non-fiction / technology. Areas are life areas (Personal, Work, Health…); this is a book taxonomy and mixing them would muddy both. |
| started | boolean |
| `started_on` | rough date, only meaningful when started |
| `percent_complete` | **buckets: 0 / 25 / 33 / 50 / 66 / 75 / 100.** Not freeform — "estimate" is the point, and a text box invites fiddling. 33 and 66 are wanted (thirds get used in practice). |
| `is_audio` | boolean. Currently far more fiction is listened to than read, and that is worth being able to see and filter. |
| rank | **per category** — each category orders independently. |

**Behaviour:**

- **Category reordering is TRANSIENT** — a UI sorting view, "bring this
  category to the top so I can work on it". It does **not** persist, so
  categories need no stored `sort_order` and there is no reorder-and-save UI.
  Cheapest correct version.
- **Finishing moves the book to `done`**, like anything else. It leaves the
  reading page.
- **Books do NOT generate next actions.** If a book needs an action
  ("finish ch. 3"), that gets captured as an ordinary task through the normal
  flow. No dependency machinery, no project linkage. This keeps the feature
  small and is the main reason it is one session rather than three.

### Commit 3 — Checklists + Technology Projects

Both reuse the ordered-list concept and should be nearly free once it exists.

- **Checklists** — recurring reference sets: what to take to work, to the dojo,
  what to consider when building a Magic deck.
- **Technology Projects** — a deliberately uncomplicated re-orderable dump
  list. No project ceremony.

**Resolved 2026-08-30 — checklists are ticked in place, and have two kinds.**

A checklist is `evergreen` true/false, and the flag decides its terminal action:

| Kind | Example | Terminal action |
|---|---|---|
| Evergreen | "Go to work", dojo bag, Magic deck considerations | **Reset** — clears the tick boxes and nothing else. Items, order and category stay put. The checklist never completes. |
| One-off | "Build the IKEA shelves" | **Complete** — the checklist goes to done and leaves the page. Never reset. |

Both are POST-redirect-GET actions on the checklist page, consistent with the
no-JS UI style.

Ticking is a checklist-local boolean, **not** `done` state. A ticked checklist
item must not move to the Done list the way a finished book does, or reset would
have to resurrect items out of `done`.

**Consequence for commit 1 — checklists need a table.** `evergreen`, and the
completed state of a one-off, are properties of *the checklist as a whole*, not
of its items. The current spec has no row for "the checklist" — categories were
going to be a plain text field on items, like `book_category`. Denormalising
`evergreen` onto every item is a bug farm: it must stay consistent across rows,
flipping it becomes a multi-row update, and an empty checklist cannot exist
because it has no row to carry the flag.

So: a small `checklists` table (`id`, `name`, `evergreen`, `status`,
`completed_at`, `created_at`), with items carrying `checklist_id` + rank. This
mirrors `projects` and does **not** violate ADR-001 — that ADR is about *lists*
being states of `items`; containers already get their own tables (`areas`,
`contexts`, `projects`). Books are unaffected: `book_category` genuinely is a
taxonomy, not a container.

**Known method drift, accepted deliberately.** A one-off checklist is, in GTD
terms, a project — a multi-step outcome finished once. This app already has
projects with a status and linked actions. The trade is the same one already
made for "Technology Projects": buying a low-ceremony container that skips
outcome / area / review_date. Consequences to keep in view:

- There will be two valid ways to represent "build the shelves".
- The Weekly Review flow will have to decide whether one-off checklists are
  reviewed as projects. Decide that *there*, not here.

**Completion is manual.** A one-off does not complete itself when its last item
is ticked; the page says all items are ticked and the human presses Complete.
Auto-completing on a tick is surprising and awkward to undo after a mis-tick,
and "disclose, don't hide" favours saying so over acting silently.

### Not in this work

**Recurring tasks** (take medication, verbally express appreciation for family)
are a genuinely different feature — repeat rules and generating the next
occurrence, touching the tickler/`defer_until` logic. **Its own session and
commit.** Do not fold it in.

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

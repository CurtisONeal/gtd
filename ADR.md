# Architecture Decision Record

Decisions that would be expensive to reverse, and why they were made. Append
new entries; don't rewrite old ones — a decision that later turned out wrong is
more useful with its original reasoning intact plus a superseding entry.

---

## ADR-001: One `items` table, not one table per list

**Status:** Accepted

**Context.** This project began after reviewing a working GTD app that used a
separate store per list (a Google Sheets tab each for inbox, next actions,
completed, etc.). That design forces every *move* to be a copy plus a delete
across two stores. Completing an action wrote a row to an archive; un-completing
had to locate and delete that row again to stay consistent. Two places to update
is where drift comes from.

**Decision.** One `items` table. Every GTD list — inbox, next actions,
waiting-for, someday/maybe, reference, done, trashed — is a value of its `state`
column.

**Consequences.**
- Moving between lists is one `UPDATE`. Complete/uncomplete are symmetric
  one-liners with no archive to reconcile.
- The lists most GTD tools skip (waiting-for, someday, reference) cost almost
  nothing — they are states, not new infrastructure.
- Left room for `defer_until` (a real tickler) with no extra table.
- Trade-off: the table is wide, and some columns only apply to some states
  (`waiting_on` is meaningless outside `waiting_for`). Accepted as cheaper than
  cross-table joins or a polymorphic scheme.

---

## ADR-002: No JavaScript dependencies at all

**Status:** Accepted (revised during implementation)

**Context.** The plan called for HTMX, vendored locally rather than from a CDN.
While building the clarify flow it became clear the flow works cleanly as plain
server-rendered forms with POST-redirect-GET.

**Decision.** Ship zero JavaScript dependencies. No framework, no HTMX, no
vendored bundle. The only client-side code is a one-line `onchange` submit on
the filter selects, which degrades to a visible button under `<noscript>`.

**Consequences.**
- No supply chain to audit, no build step, no bundle to keep updated — which
  matters more than usual for a project whose premise is "self-hosted, nothing
  leaks."
- Works with JavaScript disabled. The back button behaves. Refresh never
  double-submits.
- Trade-off: each clarify step is a page load. On localhost or a tailnet this is
  imperceptible. Over a high-latency link it would be noticeable; revisit only
  if that becomes real.

---

## ADR-003: Plain `sqlite3`, no ORM, all SQL in `store.py`

**Status:** Accepted

**Decision.** Use the stdlib `sqlite3` module directly. Confine every query to
`store.py`; no other module contains SQL.

**Consequences.**
- One fewer dependency, no session/identity-map semantics to reason about, and
  the queries are legible as queries.
- The "move to Postgres later" option stays real rather than aspirational —
  it touches the connection layer in `db.py` and the queries in `store.py`, and
  nothing else.
- Enforced in review: a `skip` route was written with inline SQL in `web.py`
  during implementation and moved into `store.py` once caught.
- Trade-off: hand-written SQL is more verbose, and column changes are manual.
  Acceptable at this schema size.

---

## ADR-004: Own the auth — argon2id and signed sessions, not third-party OAuth

**Status:** Accepted

**Context.** The reviewed app used Google OAuth, which also meant Google held
the data. A stated goal here is that no third party is involved.

**Decision.** Local accounts. Argon2id password hashes in a `users` table,
signed `HttpOnly` session cookies via Starlette's `SessionMiddleware`,
`SameSite=Lax`, and a per-IP login rate limiter.

**Consequences.**
- No identity provider, no callback URLs, no third-party outage or policy change
  can lock you out of your own task list.
- `SameSite=Lax` is also the CSRF defense: cross-site POSTs do not carry the
  cookie. No token plumbing needed for a single-user app.
- Login errors are identical whether or not the username exists.
- The password is set via `gtd set-password`, never generated or seen by tooling.
- Trade-off: no SSO, no password reset flow. For a single-user self-hosted app,
  losing the password means running `set-password` again at the machine.

---

## ADR-005: Time estimates are buckets, not free-entry minutes

**Status:** Accepted (supersedes the original number input)

**Context.** The field shipped as `<input type="number" min="1" step="5">`.
Browsers step from the *minimum*, so the spinner offered 1, 6, 11, 16, 21 —
found immediately in real use.

**Decision.** A `<select>` of durations: 2 min through a full day.

**Consequences.**
- Fixes the bug, and is a better fit for the method: GTD uses time as a
  *selection* criterion ("I have twenty minutes — what fits?"), so buckets carry
  the needed information and precise minutes do not.
- Much faster to enter on a phone than a number spinner.
- A regression test asserts no number input remains and that the offered values
  are exactly the intended set.

---

## ADR-006: Editing and undo are first-class, not optional polish

**Status:** Accepted

**Context.** The first build had no way to edit an item or reverse a completion
or deletion. A typo made during clarify was permanent. The `trashed` state
existed with no page that showed it. This surfaced within minutes of first real
use.

**Decision.** An edit page covering title, notes, every metadata field, and
moving an item between lists; restore from both `done` and `trashed`; Done and
Trash reachable from the nav, de-emphasized as recovery surfaces rather than
daily destinations.

**Consequences.**
- Deletion stays soft by default, so "undo" is always available.
- Surfaced a latent bug: `update_item` ran every value through a normalizer that
  turns `""` into `NULL`, which would have violated the `NOT NULL` constraint on
  `notes` the first time anyone saved an item with the notes field empty.
  `NOT NULL` columns now keep a string; a blank title is rejected outright.

---

## ADR-007: Tailscale for remote access, not public exposure

**Status:** Accepted

**Context.** The app needs to be reachable from a phone and other machines.
The fast alternative was a tunnel service giving a public URL in about two
minutes.

**Decision.** Tailscale. A private WireGuard mesh between the owner's own
devices; nothing is published to the internet.

**Consequences.**
- The app's login is defense in depth rather than the only thing between the
  internet and a personal task list.
- Requires the server to bind an interface Tailscale can reach — `127.0.0.1`
  will not do. `0.0.0.0` is simplest but also exposes the app to the local LAN;
  binding the `100.x.y.z` address directly is tighter but brittle if that
  address changes. Documented as an explicit choice in the README.
- `GTD_SECURE_COOKIES` stays `false` on the tailnet: traffic is encrypted at the
  WireGuard layer, but the browser still sees plain `http`, so setting the
  Secure flag would stop the cookie being sent and lock the user out. It gets
  enabled only alongside real TLS (Phase 3).

---

## ADR-008: Work instances are local-only, permanently

**Status:** Accepted

**Context.** ADR-007 chose Tailscale so a personal instance is reachable from a
phone. That reasoning does not transfer to a deployment on a work machine.
Joining a work machine to a personal tailnet would bridge two networks that
should stay separate, and would make work data reachable from personal devices.

**Decision.** A work instance is local-only, permanently. `--host 127.0.0.1`,
no Tailscale, no tunnel, no reverse proxy, no inbound exposure of any kind. It
is reachable only from the machine it runs on.

This is not a conservative default to be relaxed once it's "set up properly" —
it is the deployment mode. Personal and work instances share no database, no
`.env`, no network path, and no data.

**Consequences.**
- Remote access, offline sync and cross-device use are simply not available for
  work instances. Accepted deliberately, not a limitation to be engineered
  around later.
- The code needs no change to support this: `GTD_DB_PATH` is already
  configurable and `--host` is a launch argument. Isolation is a deployment
  choice the design already permits.
- Anything wanting to bridge the two — shared capture, a combined view — is out
  of scope by decision, not by omission.

---

## ADR-009: Lists are directly addable, not clarify-only

**Status:** Accepted (supersedes clarify-only entry in ADR-001's flow)

**Context.** Waiting For, Someday/Maybe and Reference could only be reached by
processing an inbox item through the clarify tree, or by editing an existing
item and changing its list. Neither is discoverable from those pages, and at
inbox zero there was no way into them at all. Reported after real use: "these
appear to have no way for items to be categorized this way."

**Decision.** Each of Next Actions, Waiting For, Someday and Reference gets an
"Add directly to…" form on its own page, with the fields that list actually
needs (`waiting_on` for Waiting For, notes for Reference, context for Next
Actions). Done and Trash get none — they are outcomes, not destinations.

**Consequences.**
- Capture-then-clarify remains the primary path and the recommended discipline;
  the direct form is framed on the page as the exception ("use this when you
  already know where it belongs").
- Trades a little GTD orthodoxy for the tool being usable. Forcing "I'm waiting
  on Dana for the lease" through capture and a four-question decision tree is
  friction with no methodological payoff.
- Direct-added items skip the inbox entirely — verified by test, since silently
  incrementing the inbox count would undermine inbox-zero as a signal.

---

## ADR-010: `GTD_LOCAL_ONLY` is enforced in code, not documented in prose

**Status:** Accepted

**Context.** ADR-008 established that work instances are local-only. That was
recorded in the README and in `AGENTS.md` — but nothing stopped a launch
argument, a copied plist, or a future edit from binding a public interface
anyway. A constraint that lives only in documentation is a suggestion, and this
one guards the boundary between a work machine and a personal network.

**Decision.** A `GTD_LOCAL_ONLY` setting, enforced in two independent places:

1. **`gtd serve`** refuses to bind a non-loopback host and exits non-zero, with
   a message naming ADR-008. `Settings.effective_host` also forces `127.0.0.1`
   regardless of `GTD_HOST`.
2. **A request-level guard**, registered as the outermost middleware, rejects
   any request whose peer address is not on this machine with `403` — before
   session parsing, auth, or rate limiting.

The second is what makes the guarantee hold: (1) alone is bypassed by running
`uvicorn --host 0.0.0.0` directly, which is exactly the accident this needs to
survive. Verified against a real remote connection over a tailnet, not only in
tests.

**Consequences.**
- The peer address is read from the socket (`request.client`), never from
  `X-Forwarded-For` or similar — those are client-controlled and would defeat
  the check. This means a reverse proxy in front would make every request look
  local; that is consistent with ADR-008, which forbids one on a work instance.
- Off by default. Personal instances on a tailnet are unaffected, and there is a
  test asserting that so the default can't quietly flip.
- `_is_loopback` accepts all of `127.0.0.0/8`, `::1`, and the hostname
  `localhost`, and nothing else. Notably it does **not** whitelist Starlette's
  `TestClient` default peer string `"testclient"` — a test discovering this had
  its fixture corrected rather than the production check weakened.
- A tailnet address (`100.x`) and a LAN address (`192.168.x`) are both treated
  as remote. "Local" means this machine, not this network.

---

## ADR-011: Blocked work lives in Waiting For with real item dependencies

**Status:** Accepted

**Context.** The Waiting For list originally modeled only delegated work: an
item had `state = 'waiting_for'` and a free-text `waiting_on` field such as
"Dana". That could describe task dependencies informally ("Eat cookies" waiting
on "Buy cookies"), but the app could not understand the relationship. The
blocked item was not linked to its prerequisite, the UI could not distinguish
"waiting on Dana" from "blocked by Buy cookies", and completing the prerequisite
did not make the blocked item available.

**Decision.** Blocked work remains in the existing Waiting For state, because
it is not currently actionable by the user. Add an `item_dependencies` table to
represent prerequisite item links. Keep `waiting_on` for delegated/external
waiting. Display internal blockers as "blocked by ..." and external waiting as
"waiting on ...". When completing an item clears all prerequisites for a waiting
item, move the waiting item back to Next Actions and remove the dependency
links.

**Evaluation.**
- This fits David Allen's method better than a new "Blocked" list: Waiting For
  is already the GTD bucket for reminders that cannot move until someone or
  something else acts.
- A real link table is preferable to overloading text because it enables
  unblocking behavior, avoids brittle title matching, and preserves a future
  path to multiple prerequisites.
- Auto-promoting to Next Actions on prerequisite completion is deterministic
  and local. It does not require model judgment, scheduling heuristics, or a
  background worker.
- The design deliberately stops short of a general dependency graph UI. The app
  needs "what am I waiting for?" and "what just became actionable?", not a
  project-planning engine.

**Consequences.**
- The schema gains a second relationship table, but `items.state` remains the
  list boundary. A blocked item is still one item row whose state is Waiting
  For.
- Cycles and self-dependencies are rejected so a user cannot create impossible
  wait chains.
- Project stall detection now treats either a Next Action or a Waiting For item
  as evidence that an active project has movement defined.
- If future review UX is added, it should surface auto-unblocked items clearly
  rather than making the user wonder why something reappeared.

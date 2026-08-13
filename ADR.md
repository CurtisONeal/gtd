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

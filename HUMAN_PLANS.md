# HUMAN_PLANS.md

Scratchpad for edits, ideas, and open questions. Park things here instead of
starting speculative work or losing them in chat history.

**How to use this:** add to *Inbox* freely — it's a capture surface, same idea as
the app. Things graduate to *Next up* once decided. Move to *Done* with a date so
the reasoning stays findable. Anything with a real architectural consequence
should end up in `ADR.md` when it lands.

---

## Inbox — unsorted, undecided

- Weekly Review flow. The biggest gap versus the method as written — Allen calls
  it the critical success factor, and there's currently nothing. Probably a
  guided page: stalled projects, waiting-for items older than N days, someday
  list resurfacing, inbox-to-zero check.
- Bind the service to the Tailscale address only (`100.x.y.z`) instead of
  `0.0.0.0`, so it isn't reachable from the local LAN. Brittle if that address
  changes — worth a look at whether `tailscale serve` handles this better.
- `tailscale serve` for real TLS on the `*.ts.net` name, which would then allow
  `GTD_SECURE_COOKIES=true`.
- Someday/Maybe review cadence — items go in and currently nothing brings them
  back out.
- Keyboard shortcuts for the clarify flow (y/n and 1/2/3 on the decision steps).
  Would speed up inbox processing a lot, but see AGENTS.md constraint 2 — needs
  thought about whether it can be done without a JS dependency.
- Recurring items. Deliberately absent so far; GTD proper handles these with a
  tickler, which `defer_until` already provides. Decide whether true recurrence
  is wanted or whether the tickler is sufficient.
- Full-text search across all lists.
- Bulk operations (select several inbox items, file them all as reference).

## Next up — decided, not built

- **Discord capture.** `POST /api/capture` is built and tested but disabled
  until `GTD_CAPTURE_TOKEN` is set. Blocked on a Discord bot token for the
  separate `direct_scripts_bot` project. Once live: `/capture <text>` from a
  phone straight into the inbox.
- **Work instance.** A second, isolated deployment for work — separate machine,
  separate database, no shared data. Nothing in the code prevents this today
  (`GTD_DB_PATH` is already configurable); it needs no changes, just a separate
  checkout and `.env`.

## Done

- 2026-08-12 — Initial build: capture, full clarify tree, all GTD lists,
  projects, auth, markdown export, 81 tests.
- 2026-08-13 — Time estimates fixed (were 1, 6, 11, 16 — a `min`/`step`
  interaction). See ADR-005.
- 2026-08-13 — Editing and undo added after both were found missing in real
  use. See ADR-006.
- 2026-08-13 — launchd service so the server survives terminal close and
  reboot; Tailscale for remote access. See ADR-007.

---

## Open questions

- **Does the two-minute rule actually get used?** It's implemented as a clarify
  step, but if in practice everything gets deferred, the step is friction. Worth
  watching before adding anything else to that flow.
- **Are areas of focus and projects both earning their keep,** or is one enough
  at this scale?
- **Horizons above areas of focus** (goals, vision, purpose — Allen's H3–H5) are
  entirely absent. Deliberate for now: they're review artifacts more than daily
  ones. Revisit if the Weekly Review flow gets built.

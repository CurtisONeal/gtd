# HUMAN_PLANS.md

Scratchpad for edits, ideas, and open questions. Park things here instead of
starting speculative work or losing them in chat history.

**How to use this:** add to *Inbox* freely — it's a capture surface, same idea as
the app. Things graduate to *Next up* once decided. Move to *Done* with a date so
the reasoning stays findable. Anything with a real architectural consequence
should end up in `ADR.md` when it lands.

---

## Inbox — unsorted, undecided

- Weekly Review flow. Still the biggest gap versus the method as written — Allen
  calls it the critical success factor, and there's currently nothing. Probably a
  guided page: stalled projects, waiting-for items older than N days, someday
  list resurfacing, inbox-to-zero check.
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

- **Discord capture.** `POST /api/capture` is built and tested but disabled
  until `GTD_CAPTURE_TOKEN` is set. Blocked on a Discord bot token for the
  separate `direct_scripts_bot` project. Once live: `/capture <text>` from a
  phone straight into the inbox.
- **Deploy the work instance.** Design and enforcement are done (see below);
  what remains is the deployment itself on the work machine: clone, `init-db`,
  `set-password`, set `GTD_LOCAL_ONLY=true`, `gtd serve`. Separate `.env` and
  `GTD_DB_PATH`; no shared data with the personal instance, ever.
- **Phone onto the tailnet.** Install Tailscale on the phone and sign in with the
  same account, then `http://octobobs-mac-mini.tail7ccdf0.ts.net:8765`. Use the
  DNS name rather than the raw IP — it survives the address changing.

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

---

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

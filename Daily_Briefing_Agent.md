# Daily_Briefing_Agent.md

Handoff for the scheduled Claude session that renders a daily brief from GTD.

Written 2026-08-30. **Read this before changing how the brief gets its data** —
the obvious approach (curl the GTD API) does not work, for reasons that are not
obvious from outside the repo.

---

## The short version

**Do not try to reach GTD over HTTP. Run `gtd export`, refresh the vault
mirror, and read from there.**

```bash
cd /Users/s_admin/dev/gtd && .venv/bin/gtd export \
  && cp exports/*.md exports/_manifest.json \
     ~/Documents/obsidian_vault/syncing_vault2_clean_2026/050_daily_operations/gtd_exports/
# then read the vault copy — ONE source, see "Two copies exist" below
```

No token, no auth, no network call, no new endpoints. Takes well under a second.

Reading the vault copy rather than `exports/` directly is deliberate: you can
already see Obsidian, and refreshing the mirror as part of the brief keeps it
current for a human too instead of letting it drift.

**The `&&` matters.** If the export fails the copy must not run — otherwise a
good mirror gets overwritten with nothing, or worse, half of something.

---

## Why not the API — three separate blockers

### 1. There is no read API. At all.

`POST /api/capture` is the **only** JSON endpoint in the application. It is
write-only: it creates an inbox item and returns `{"id": …, "title": …}`.

Every read route returns **HTML for a browser, behind session-cookie auth**:

```
GET /              GET /inbox        GET /list/{state}
GET /projects      GET /items/{id}/edit
```

A brief needs to *read* next actions, waiting-for, and overdue items. Nothing
in the current surface returns that as data.

### 2. The capture token was never actually set

A previous session believed one had been configured. It has not:

```
.env line 6:   GTD_CAPTURE_TOKEN=          ← present but EMPTY
live server:   POST /api/capture → 404 {"error":"capture api disabled"}
```

`settings.capture_api_enabled` is false whenever the token is empty, so the
endpoint 404s before it ever checks credentials. **Setting the token would not
help anyway** — see blocker 1. It would grant the ability to create tasks, not
read them.

### 3. Local-only is a deliberate constraint, not an obstacle to route around

`GTD_LOCAL_ONLY` is enforced in two places (`gtd serve` refuses a public bind;
the outermost middleware rejects non-loopback peers, reading the address from
the socket and never from a header). See ADR-010 and AGENTS.md constraint 8.

Tailscale does not change this and is not the missing piece: reachability was
never the blocker. The read surface is HTML-for-humans.

---

## The device binding is the right call

Binding the trigger with `requires_local_device: true` so it runs on
**octobobs-mini** is correct — and once it does, the export path needs no
network at all. That is the whole design intent of ADR-008/ADR-010: the data
stays on the machine.

Note the constraint that forced the recreate: `requires_local_device` can only
be set at trigger *creation*, not edited afterwards. Deleting and recreating
the trigger while the session is linked to Octobob is the way to bind it.

---

## What the export actually gives you

`gtd export` writes seven files to `exports/` (path from `GTD_EXPORT_DIR`):

| File | Contents |
|---|---|
| `inbox.md` | uncla­rified captures |
| `next_action.md` | **the brief's main source** |
| `waiting_for.md` | delegated / blocked, with `waiting on …` |
| `someday.md` | someday-maybe |
| `reference.md` | reference material |
| `projects.md` | projects, incl. **⚠ Stalled** (no next action) |
| `_manifest.json` | freshness + counts — **check this first** |

Real sample (`next_action.md`):

```markdown
# Next Actions

_17 items — generated 2026-08-30 17:17_

- [ ] Go pump up tire  _(@home · 💪 Health · energy: medium · 10m · P2 · due 2026-08-27 ⚠ OVERDUE)_
- [ ] Make a new magic deck  _(@home · ↳ Straighten magic cards · 🎨 Creative · energy: medium · 90m · P2 · due 2026-09-06)_
```

Everything a brief needs is already inline: **context** (`@home`, `@computer`),
**energy**, **time estimate**, **priority**, **due date with an explicit
`⚠ OVERDUE` marker**, and **parent project** (`↳`).

The `⚠ OVERDUE` marker matters — it means the brief does not need to parse and
compare dates itself, and cannot get that comparison wrong.

`Trash` is deliberately excluded from export. `Done` is not exported either.

---

## Freshness — check it, do not assume it

**The export is a snapshot, not a live view.** Files reflect the moment
`gtd export` last ran. A brief that reads stale files reports yesterday's list
with total confidence — the failure is silent and looks exactly like success.

**Always run `gtd export` in the same run that reads it.** Never depend on a
separately-scheduled export, and never assume files are current because they
exist.

**Then verify rather than trusting the sequencing.** Every export carries a
machine-readable timestamp, and `_manifest.json` collects them in one place:

```json
{
  "generated_at": "2026-08-30T17:39:36-04:00",
  "files": ["inbox.md", "next_action.md", "..."],
  "counts": {"inbox": 2, "next_action": 17, "waiting_for": 2}
}
```

Each `.md` file also carries its own marker, so a single file is
self-describing even if separated from the manifest:

```
<!-- generated_at: 2026-08-30T17:39:36-04:00 -->
```

**Before rendering the brief: parse `generated_at`, and abort if it is more
than a few minutes old.** Say the export is stale rather than producing a
confident brief from old data. Timestamps carry a UTC offset so this works
regardless of which machine reads them.

`_manifest.json` is written **last**, so a partially-written export leaves the
manifest absent or older than the files — a reader that checks it fails closed
rather than treating a half-written set as current.

---

## Two copies exist — do not double-count

There are two sets of the same files:

```
~/dev/gtd/exports/                                     ← written by `gtd export`
…/050_daily_operations/gtd_exports/                    ← the vault mirror
```

**They are the same lists, not two sources.** Read exactly one — the vault copy,
per the command above. Reading both and merging produces a brief that reports
every task twice, and because the content is genuinely identical the duplication
looks like real duplicate tasks in GTD rather than a bug in the brief.

If the two disagree, the mirror is stale and the fix is to re-run the
export-and-copy, never to reconcile them by hand.

Nothing syncs the mirror automatically; the `&&` chain above is what keeps it
current.

---

## Rules this agent must not break

From `AGENTS.md`, and they apply to anything reading GTD:

- **Nothing leaves the machine.** No telemetry, no third-party API, no external
  asset loads. The data is the point.
- **Never commit `.env`, `*.db`, or `exports/`.** All gitignored. This repo is
  public.
- **Never read the peer address from a header** if you touch the web layer.
- **No LLM calls in the GTD core.** A brief is judgment work and lives
  *outside* the app — reading exported files is exactly the right shape for
  that boundary.

---

## If a read API is genuinely needed later

Only worth it if the brief must run from a machine that is **not** Octobob.
Scoped estimate is in `HUMAN_PLANS.md` under "Read API for agents". Short
version: **1–2 sessions**, and it is real work, not a small addition — routes,
token auth, serialisation, tests, and it must respect the local-only guard.

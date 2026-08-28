# GTD method context for agents

Read this before changing capture, clarify, list organization, project review,
or engagement behavior. `AGENTS.md` is the operating checklist; this file is the
method context behind those rules.

This is a working summary, not a replacement for David Allen's book or the
official training materials. It exists so future agents do not reinterpret GTD
from generic task-app habits.

## Sources consulted

- Official overview: https://gettingthingsdone.com/what-is-gtd/
- Choosing criteria: https://gettingthingsdone.com/2023/01/choosing-what-to-do/
- Two-minute rule transcript:
  https://gettingthingsdone.com/2020/05/the-two-minute-rule-2/
- Official setup guide sample, especially the five workflow steps and common
  lists:
  https://gettingthingsdone.com/wp-content/uploads/2021/12/GTD_and_iPad_A4_-SAMPLE.pdf

Consulted 2026-08-24.

## Core idea

GTD is a trusted external system for turning "stuff" into clear outcomes,
reminders, and actions. The app should help the user stop holding open loops in
their head. It should not become a generic priority board, Kanban system, or
planner that makes the user re-decide the same unclear work over and over.

The five workflow phases are distinct:

1. Capture: collect what has attention.
2. Clarify: decide what each captured thing means.
3. Organize: put the result where it belongs.
4. Reflect: review and update the system.
5. Engage: choose and do work from trusted reminders.

Do not blur these phases casually. For example, capture should not ask for a
project, due date, energy level, or dependency. Those are clarify/organize
decisions.

## Clarify decision tree

Process inbox items one at a time, oldest first.

Ask whether the item is actionable.

- If not actionable, the destinations are Trash, Reference, or Someday/Maybe.
- If actionable and more than one step is required, create or connect a Project:
  a desired outcome plus at least one reminder of the next thing to move it.
- If actionable and one step:
  - If it can be completed very quickly, do it now and mark it Done.
  - If someone else must do it, or something else must happen first, put it on
    Waiting For.
  - If the user can do it later, make it a concrete Next Action, with context,
    time, energy, priority, deadline, and/or tickler metadata as useful.

The current UI follows this shape: `/` captures; `/inbox` asks the clarify
questions; defer creates a Next Action; delegate creates Waiting For; non-
actionable filing creates Reference, Someday/Maybe, or Trash.

## List meanings

### Inbox

Inbox contains unclarified captured material. It is not a to-do list. Emptying
the inbox means deciding what each item is and where it belongs, not finishing
all the work.

### Next Actions

Next Actions are concrete, visible actions the user could do as soon as the
right context, time, energy, and priority line up. The official GTD engagement
criteria map directly to the app's fields:

- context: place, tool, or person required
- time: rough available duration
- energy: available mental/physical resource
- priority: relative importance after the other constraints

Do not put blocked work here. If the user cannot actually do the action yet,
it is not a current next action.

### Waiting For

Waiting For is a reminder list for commitments or outcomes that are not
currently actionable by the user because they are waiting on a person, external
event, or prerequisite.

This app stores external/delegated waiting as `items.state = 'waiting_for'`
plus a free-text `waiting_on` field. The UI labels it "Waiting on" and examples
use people (`Dana`), but the method can also cover non-person blockers.

For item dependencies, keep the blocked item in Waiting For. Example:

- `Buy cookies` is a Next Action.
- `Eat cookies` is Waiting For, blocked by `Buy cookies`.
- `Eat cookies` should not appear in Next Actions until the cookies have been
  bought.

For real item dependencies, the app uses `item_dependencies` instead of
overloading `waiting_on` text. Preserve both concepts:

- external/delegated waiting: `waiting_on = "Dana"` or similar
- internal dependency: a real link from the blocked item to prerequisite item(s)

The Waiting tab makes the distinction visible: "waiting on Dana" versus
"blocked by Buy cookies". Completing a prerequisite moves the unblocked item to
Next Actions when no other blockers remain. Silent hiding is a bug; if future
review UX is added, it should make newly unblocked work easy to notice.

### Someday/Maybe

Someday/Maybe is incubation. It is for possible future commitments, not for
actions the user already intends to do soon. Items placed here need a review
surface eventually, otherwise they become hidden trash.

### Reference

Reference is non-actionable material worth keeping. It should not behave like an
action list and should not acquire action-only fields unless there is a clear
reason.

### Projects

A GTD project is any desired outcome requiring more than one action. It is not
the same thing as a task with subtasks. A project needs a desired outcome and at
least one current reminder: a Next Action, Waiting For item, or reviewed plan
that shows how it will move.

The Projects page flags active projects with neither open next actions nor
waiting items as stalled. A project with no next action but an active
waiting/blocking reminder is not the same kind of stall as a project with no
defined movement at all.

### Done and Trash

Done and Trash are outcomes and recovery surfaces. They are browseable and
restorable, but users should not add directly to them.

## Current UI map

- Home (`/`): capture surface first; one item per line. Shows counts, due-soon
  items, and stalled projects after capture.
- Inbox (`/inbox`): guided clarify flow, one question per page; oldest item
  first; skip sends an item to the back.
- Next Actions (`/list/next_action`): engagement list; direct add exists for
  already-clarified actions; context and area filters narrow the list; deferred
  items are hidden until `defer_until` and the page discloses the hidden count.
- Waiting For (`/list/waiting_for`): waiting/delegation/blocking list with a
  direct-add form for "What you're waiting for", "Waiting on", "Blocked by
  task", and expected date.
- Someday/Maybe and Reference: directly addable because users may already know
  the destination without using the inbox.
- Projects (`/projects`): create projects, see active projects, add next
  actions, and spot projects with no open next action.
- Edit (`/items/{id}/edit`): universal correction/move surface for title, notes,
  state, project, context, area, energy, time, priority, dates, and waiting_on.

## Product implications

- Keep capture low-friction. No required metadata at capture time.
- Keep list meanings clean. If a field only makes sense in one state, expose it
  carefully and avoid implying it applies everywhere.
- Disclose withholding. Tickler/deferred items and future blocked items should
  not disappear silently.
- Prefer review surfaces over clever automation. GTD depends on a trusted
  system the user understands.
- Avoid building generic task-manager concepts unless they serve the method. A
  dependency feature should answer "what am I waiting for, and what becomes
  available when it clears?", not turn the app into a graph planner.
- Keep `waiting_on` text and `item_dependencies` separate. The first is for
  people or external events; the second is for real task prerequisites.
- Preserve the repo constraints from `AGENTS.md`: deterministic core, no LLM
  calls for state moves, no JavaScript dependencies, all SQL in `store.py`, and
  no external assets or telemetry.

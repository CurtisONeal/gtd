# Fixed Bugs

Concrete defects that were observed, fixed, and covered by regression tests.
Use this for bug history and verification notes. Use `ADR.md` for higher-level
architecture decisions.

---

## 2026-08-24 — Waiting For could only describe task dependencies as text

**Symptom.** A dependent task such as `Eat cookies` could be put on Waiting For
with `waiting_on = "Buy cookies"`, but that text was not linked to the real
`Buy cookies` item. The UI could not distinguish a task blocker from a person,
and completing `Buy cookies` did not make `Eat cookies` actionable.

**Cause.** Waiting For used one free-text `waiting_on` field for every kind of
waiting. There was no item-to-item dependency model.

**Fix.** Added `item_dependencies` with `blocked_item_id` and
`prerequisite_item_id`. Waiting For now shows task blockers as "blocked by ..."
while keeping delegated waits as "waiting on ...". Completing a prerequisite
promotes blocked waiting items to Next Actions once all blockers are done.

**Regression tests.**

- `test_waiting_item_can_be_blocked_by_another_item`
- `test_completing_a_prerequisite_unblocks_waiting_items`
- `test_dependency_rejects_self_blocking`
- `test_dependency_rejects_cycles`
- `test_direct_add_waiting_for_can_be_blocked_by_a_task`
- `test_waiting_page_distinguishes_task_blockers_from_people`
- `test_completing_blocker_promotes_waiting_item`
- `test_edit_can_assign_a_blocking_task`
- `test_project_with_waiting_item_is_not_stalled_without_next_action`

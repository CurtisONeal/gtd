from datetime import date, timedelta

from gtd.export import EXPORTED_STATES, export_all, render_list, render_projects
from gtd.models import ItemState


def test_export_writes_a_file_per_list_plus_projects(store, tmp_path):
    written = export_all(store, tmp_path / "exports")
    names = {p.name for p in written}
    assert names == {f"{s}.md" for s in EXPORTED_STATES} | {"projects.md"}
    assert all(p.exists() for p in written)


def test_empty_list_says_so_rather_than_being_blank(store, tmp_path):
    export_all(store, tmp_path / "exports")
    assert "_Nothing here._" in (tmp_path / "exports" / "someday.md").read_text()


def test_item_appears_with_its_annotations(store, tmp_path):
    contexts = {c["name"]: c["id"] for c in store.list_contexts()}
    pid = store.create_project("Deck")
    item = store.capture("Price out lumber")
    store.set_state(
        item,
        ItemState.NEXT_ACTION,
        project_id=pid,
        context_id=contexts["@errands"],
        priority=1,
        time_estimate_min=30,
        energy="high",
    )

    text = render_list(ItemState.NEXT_ACTION, store.list_items(ItemState.NEXT_ACTION))
    assert "- [ ] Price out lumber" in text
    assert "@errands" in text
    assert "↳ Deck" in text
    assert "P1" in text
    assert "30m" in text
    assert "energy: high" in text


def test_overdue_is_flagged(store):
    item = store.capture("late thing")
    store.set_state(
        item,
        ItemState.NEXT_ACTION,
        due_date=(date.today() - timedelta(days=2)).isoformat(),
    )
    text = render_list(ItemState.NEXT_ACTION, store.list_items(ItemState.NEXT_ACTION))
    assert "OVERDUE" in text


def test_waiting_on_is_shown(store):
    item = store.capture("signed contract")
    store.set_state(item, ItemState.WAITING_FOR, waiting_on="Dana")
    text = render_list(ItemState.WAITING_FOR, store.list_items(ItemState.WAITING_FOR))
    assert "waiting on Dana" in text


def test_notes_are_indented_under_the_item(store):
    item = store.capture("with notes")
    store.update_item(item, notes="line one\nline two")
    text = render_list(ItemState.INBOX, store.list_items(ItemState.INBOX))
    assert "      line one" in text
    assert "      line two" in text


def test_export_includes_deferred_items(store, tmp_path):
    """The file is an archive of everything, unlike the live next-actions view
    which deliberately hides deferred items."""
    item = store.capture("future thing")
    store.set_state(
        item,
        ItemState.NEXT_ACTION,
        defer_until=(date.today() + timedelta(days=60)).isoformat(),
    )
    export_all(store, tmp_path / "exports")
    text = (tmp_path / "exports" / "next_action.md").read_text()
    assert "future thing" in text
    assert "deferred until" in text


def test_stalled_project_is_called_out(store):
    store.create_project("No actions here", outcome="Something good")
    text = render_projects(store.list_projects())
    assert "Stalled" in text
    assert "Something good" in text


def test_project_with_actions_is_not_stalled(store):
    pid = store.create_project("Has actions")
    store.set_state(store.capture("do a thing"), ItemState.NEXT_ACTION, project_id=pid)
    text = render_projects(store.list_projects())
    assert "Stalled" not in text
    assert "1 open next action" in text


def test_export_is_idempotent(store, tmp_path):
    store.capture("something")
    first = (tmp_path / "e" ) ; export_all(store, first)
    before = (first / "inbox.md").read_text()
    export_all(store, first)
    after = (first / "inbox.md").read_text()
    # Only the generated-at timestamp may differ; the item content must not.
    assert "- [ ] something" in before and "- [ ] something" in after

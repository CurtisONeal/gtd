"""Checklists: an ordered list with a container, run rather than done.

The distinction that matters is evergreen vs one-off. They share a shape and
differ only in their terminal action, and `ticked` must never be the `done`
state — reset would otherwise have to resurrect rows out of Done.
"""

import pytest

from gtd.models import ChecklistStatus, ItemState


@pytest.fixture
def dojo(store):
    """An evergreen list with three items, the middle one ticked."""
    checklist_id = store.create_checklist("Dojo bag", evergreen=True)
    ids = [store.add_checklist_item(checklist_id, t) for t in ["gi", "belt", "water"]]
    store.set_ticked(ids[1], True)
    return checklist_id, ids


def test_items_keep_their_order_and_rank_within_the_list(store, dojo):
    checklist_id, ids = dojo
    assert [i["title"] for i in store.list_checklist_items(checklist_id)] == [
        "gi", "belt", "water"
    ]

    store.move_in_order(ids[2], -1, group="checklist_id")

    assert [i["title"] for i in store.list_checklist_items(checklist_id)] == [
        "gi", "water", "belt"
    ]


def test_each_checklist_orders_independently(store, dojo):
    checklist_id, _ = dojo
    other = store.create_checklist("Work bag")
    first = store.add_checklist_item(other, "laptop")

    assert store.move_in_order(first, -1, group="checklist_id") is False
    assert [i["title"] for i in store.list_checklist_items(other)] == ["laptop"]


def test_ticking_is_not_the_done_state(store, dojo):
    """The whole reason reset works: a ticked item stays a checklist item."""
    checklist_id, ids = dojo
    item = store.get_item(ids[1])

    assert item["ticked"] == 1
    assert item["state"] == ItemState.CHECKLIST
    assert store.list_items(ItemState.DONE) == []


def test_reset_clears_ticks_and_keeps_everything_else(store, dojo):
    checklist_id, ids = dojo
    store.set_ticked(ids[0], True)

    assert store.reset_checklist(checklist_id) is True

    items = store.list_checklist_items(checklist_id)
    assert [i["title"] for i in items] == ["gi", "belt", "water"]
    assert all(i["ticked"] == 0 for i in items)
    assert [i["rank"] for i in items] == [0, 1, 2]


def test_an_evergreen_list_never_completes(store, dojo):
    checklist_id, _ = dojo
    assert store.complete_checklist(checklist_id) is False
    assert store.get_checklist(checklist_id)["status"] == ChecklistStatus.ACTIVE


def test_a_one_off_completes_and_is_never_reset(store):
    checklist_id = store.create_checklist("Build the shelves", evergreen=False)
    store.add_checklist_item(checklist_id, "buy brackets")

    assert store.reset_checklist(checklist_id) is False, "one-offs do not reset"
    assert store.complete_checklist(checklist_id) is True

    checklist = store.get_checklist(checklist_id)
    assert checklist["status"] == ChecklistStatus.DONE
    assert checklist["completed_at"]


def test_a_completed_one_off_leaves_the_active_index(store):
    checklist_id = store.create_checklist("Build the shelves", evergreen=False)
    store.complete_checklist(checklist_id)

    assert checklist_id not in [c["id"] for c in store.list_checklists()]
    assert checklist_id in [c["id"] for c in store.list_checklists(status="done")]


def test_reopening_a_one_off_clears_its_completion(store):
    checklist_id = store.create_checklist("Build the shelves", evergreen=False)
    store.complete_checklist(checklist_id)

    store.reopen_checklist(checklist_id)

    checklist = store.get_checklist(checklist_id)
    assert checklist["status"] == ChecklistStatus.ACTIVE
    assert checklist["completed_at"] is None


def test_deleting_a_checklist_takes_its_items(store, dojo):
    checklist_id, ids = dojo
    store.delete_checklist(checklist_id)

    assert store.get_checklist(checklist_id) is None
    assert store.get_item(ids[0]) is None, "the FK should cascade"


def test_the_index_reports_tick_progress(store, dojo):
    checklist_id, _ = dojo
    row = next(c for c in store.list_checklists() if c["id"] == checklist_id)

    assert row["item_count"] == 3
    assert row["ticked_count"] == 1


def test_checklist_items_stay_out_of_the_actionable_lists(store, dojo):
    for state in ItemState.user_lists():
        assert store.list_items(state) == []


def test_a_checklist_needs_a_name(store):
    with pytest.raises(ValueError, match="name cannot be empty"):
        store.create_checklist("   ")


# ── Routes ───────────────────────────────────────────────────────────────────


def test_creating_a_checklist_lands_on_its_page(signed_in, app):
    response = signed_in.post(
        "/checklists", data={"name": "Dojo bag", "evergreen": "1"}, follow_redirects=False
    )

    checklist_id = app.state.store.list_checklists()[0]["id"]
    assert response.headers["location"] == f"/checklists/{checklist_id}"


def test_a_one_off_is_created_when_evergreen_is_unchecked(signed_in, app):
    """An unchecked checkbox sends nothing at all, which must mean one-off."""
    signed_in.post("/checklists", data={"name": "Build the shelves"})

    assert app.state.store.list_checklists()[0]["evergreen"] == 0


def test_ticking_and_unticking_through_the_form(signed_in, app):
    store = app.state.store
    checklist_id = store.create_checklist("Dojo bag")
    item_id = store.add_checklist_item(checklist_id, "gi")

    signed_in.post(f"/checklists/{checklist_id}/items/{item_id}/tick", data={"ticked": "1"})
    assert store.get_item(item_id)["ticked"] == 1

    signed_in.post(f"/checklists/{checklist_id}/items/{item_id}/tick", data={})
    assert store.get_item(item_id)["ticked"] == 0


def test_reset_route_only_offered_for_evergreen(signed_in, app):
    store = app.state.store
    evergreen = store.create_checklist("Dojo bag", evergreen=True)
    one_off = store.create_checklist("Build the shelves", evergreen=False)

    assert "Reset ticks" in signed_in.get(f"/checklists/{evergreen}").text
    body = signed_in.get(f"/checklists/{one_off}").text
    assert "Reset ticks" not in body
    assert "Move to Done" in body


def test_a_fully_ticked_one_off_is_not_completed_automatically(signed_in, app):
    """Completion is manual — the page says so rather than acting on its own."""
    store = app.state.store
    checklist_id = store.create_checklist("Build the shelves", evergreen=False)
    item_id = store.add_checklist_item(checklist_id, "buy brackets")

    signed_in.post(f"/checklists/{checklist_id}/items/{item_id}/tick", data={"ticked": "1"})

    assert store.get_checklist(checklist_id)["status"] == ChecklistStatus.ACTIVE
    assert "Everything is ticked" in signed_in.get(f"/checklists/{checklist_id}").text


def test_generic_list_page_redirects_checklist_items(signed_in):
    response = signed_in.get("/list/checklist", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/checklists"


def test_a_missing_checklist_redirects_rather_than_500s(signed_in):
    response = signed_in.get("/checklists/9999", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/checklists"

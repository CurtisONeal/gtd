"""Technology projects: the ordered-list concept with nothing added.

Worth testing precisely because it adds nothing — if this needs code beyond
routes and a template, the shared concept is not carrying its weight.
"""

from gtd.models import ItemState


def titles(store):
    return [row["title"] for row in store.list_ordered(ItemState.TECH_PROJECT)]


def test_items_append_and_reorder(store):
    ids = [
        store.append_to_ordered(t, ItemState.TECH_PROJECT)
        for t in ["rebuild the NAS", "try nix", "learn zig"]
    ]
    assert titles(store) == ["rebuild the NAS", "try nix", "learn zig"]

    store.move_in_order(ids[2], -1)

    assert titles(store) == ["rebuild the NAS", "learn zig", "try nix"]


def test_completing_one_removes_it_from_the_list(store):
    item_id = store.append_to_ordered("rebuild the NAS", ItemState.TECH_PROJECT)
    store.complete(item_id)

    assert titles(store) == []
    assert store.get_item(item_id)["state"] == ItemState.DONE


def test_tech_projects_stay_out_of_the_actionable_lists(store):
    store.append_to_ordered("try nix", ItemState.TECH_PROJECT)

    for state in ItemState.user_lists():
        assert store.list_items(state) == []


def test_ordering_is_separate_from_books_and_checklists(store):
    """All three are ordered lists, so a shared rank scope would tangle them."""
    from gtd.models import BookCategory

    store.add_book("SICP", book_category=BookCategory.TECHNOLOGY)
    tech = store.append_to_ordered("try nix", ItemState.TECH_PROJECT)

    assert store.move_in_order(tech, -1) is False, "alone in its own list"
    assert titles(store) == ["try nix"]


def test_add_and_move_through_the_forms(signed_in, app):
    store = app.state.store
    signed_in.post("/tech/add", data={"title": "rebuild the NAS"})
    signed_in.post("/tech/add", data={"title": "try nix"})

    second = store.list_ordered(ItemState.TECH_PROJECT)[1]["id"]
    signed_in.post(f"/tech/{second}/move", data={"delta": "-1"})

    assert titles(store) == ["try nix", "rebuild the NAS"]


def test_blank_titles_are_ignored(signed_in, app):
    signed_in.post("/tech/add", data={"title": "   "})

    assert app.state.store.list_ordered(ItemState.TECH_PROJECT) == []


def test_generic_list_page_redirects_to_the_tech_page(signed_in):
    response = signed_in.get("/list/tech_project", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/tech"

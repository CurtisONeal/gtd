"""Books: an ordered list specialised with progress fields."""

import pytest

from gtd.models import PERCENT_BUCKETS, BookCategory, ItemState


@pytest.fixture
def books(store):
    return [
        store.add_book("Dune", book_category=BookCategory.FICTION),
        store.add_book("Neuromancer", book_category=BookCategory.FICTION),
        store.add_book("SICP", book_category=BookCategory.TECHNOLOGY),
    ]


def shelf(store, category):
    return [
        row["title"] for row in store.list_books() if row["book_category"] == category
    ]


def test_each_category_orders_independently(store, books):
    """Ranking is per category — moving a book must not disturb another shelf."""
    assert shelf(store, BookCategory.FICTION) == ["Dune", "Neuromancer"]
    assert shelf(store, BookCategory.TECHNOLOGY) == ["SICP"]

    store.move_in_order(books[1], -1, group="book_category")

    assert shelf(store, BookCategory.FICTION) == ["Neuromancer", "Dune"]
    assert shelf(store, BookCategory.TECHNOLOGY) == ["SICP"]


def test_a_book_cannot_be_moved_past_its_own_shelf(store, books):
    """SICP is first in Technology even though books above it exist in Fiction."""
    assert store.move_in_order(books[2], -1, group="book_category") is False


def test_finishing_a_book_removes_it_from_the_reading_list(store, books):
    store.complete(books[0])

    assert "Dune" not in [row["title"] for row in store.list_books()]
    assert store.get_item(books[0])["state"] == ItemState.DONE


def test_starting_a_book_records_a_date_and_unstarting_clears_it(store, books):
    store.set_book_progress(books[0], started=True)
    item = store.get_item(books[0])
    assert item["started"] == 1
    assert item["started_on"]

    store.set_book_progress(books[0], started=False)
    item = store.get_item(books[0])
    assert item["started"] == 0
    assert item["started_on"] is None, "a start date must not outlive the flag"


def test_restarting_keeps_the_original_start_date(store, books):
    store.set_book_progress(books[0], started=True)
    store.update_item(books[0], started_on="2020-01-01")
    store.set_book_progress(books[0], started=True, percent_complete=50)

    assert store.get_item(books[0])["started_on"] == "2020-01-01"


def test_boolean_flags_never_become_null(store, books):
    """`started` and `is_audio` are NOT NULL. `_clean` turns a blank form value
    into NULL, which would violate the constraint — the documented trap."""
    store.update_item(books[0], started="", is_audio="")

    item = store.get_item(books[0])
    assert item["started"] == 0
    assert item["is_audio"] == 0


def test_audio_is_recorded(store):
    book_id = store.add_book("Project Hail Mary", book_category=BookCategory.FICTION, is_audio=True)
    assert store.get_item(book_id)["is_audio"] == 1


def test_books_do_not_appear_in_the_actionable_lists(store, books):
    """Books sit outside the actionable flow — they must not leak into next
    actions, and they are not a browsable generic list."""
    for state in ItemState.user_lists():
        assert store.list_items(state) == []
    assert ItemState.BOOK not in ItemState.user_lists()


def test_percent_buckets_include_thirds_and_are_sane(store):
    """Regression on the shape of the buckets, not just their presence: thirds
    are wanted, and the range must be 0-100 ascending."""
    assert 33 in PERCENT_BUCKETS and 66 in PERCENT_BUCKETS
    assert PERCENT_BUCKETS[0] == 0 and PERCENT_BUCKETS[-1] == 100
    assert list(PERCENT_BUCKETS) == sorted(PERCENT_BUCKETS)


# ── Routes ───────────────────────────────────────────────────────────────────


def test_books_page_lists_by_category(signed_in, app):
    client = signed_in
    store = app.state.store
    store.add_book("Dune", book_category=BookCategory.FICTION)
    store.add_book("SICP", book_category=BookCategory.TECHNOLOGY)

    body = client.get("/books").text
    assert "Dune" in body and "SICP" in body
    assert "General Non-fiction" in body, "empty shelves still show"


def test_adding_a_book_through_the_form(signed_in, app):
    client = signed_in
    client.post(
        "/books/add",
        data={"title": "Piranesi", "book_category": "fiction", "is_audio": "1"},
    )

    rows = app.state.store.list_books()
    assert [r["title"] for r in rows] == ["Piranesi"]
    assert rows[0]["is_audio"] == 1


def test_adding_a_book_with_an_unknown_category_is_rejected(signed_in, app):
    client = signed_in
    client.post("/books/add", data={"title": "Nope", "book_category": "cookbooks"})

    assert app.state.store.list_books() == []


def test_moving_a_book_through_the_form(signed_in, app):
    client = signed_in
    store = app.state.store
    store.add_book("first", book_category=BookCategory.FICTION)
    second = store.add_book("second", book_category=BookCategory.FICTION)

    client.post(f"/books/{second}/move", data={"delta": "-1"})

    assert [r["title"] for r in store.list_books()] == ["second", "first"]


def test_finish_route_completes_and_marks_fully_read(signed_in, app):
    client = signed_in
    store = app.state.store
    book_id = store.add_book("Dune", book_category=BookCategory.FICTION)

    client.post(f"/books/{book_id}/finish")

    item = store.get_item(book_id)
    assert item["state"] == ItemState.DONE
    assert item["percent_complete"] == 100
    assert store.list_books() == []


def test_progress_route_rejects_a_percent_outside_the_buckets(signed_in, app):
    client = signed_in
    store = app.state.store
    book_id = store.add_book("Dune", book_category=BookCategory.FICTION)

    client.post(f"/books/{book_id}/progress", data={"percent_complete": "37", "started": "1"})

    assert store.get_item(book_id)["percent_complete"] == 0, "37 is not a bucket"


def test_generic_list_page_redirects_books_to_their_own_page(signed_in):
    client = signed_in
    response = client.get("/list/book", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/books"


def test_only_one_control_reads_as_completion(signed_in, app):
    """Three controls looked like "done": the 100% bucket, Save, and a bare ✓.
    Only one of them completes a book, and the page must say which.
    """
    client = signed_in
    app.state.store.add_book("Dune", book_category=BookCategory.FICTION)

    body = client.get("/books").text

    assert "Move to Done" in body
    assert ">Save progress<" in body, "the progress button must not read as completion"


def test_a_book_at_100_percent_is_not_finished_and_says_so(signed_in, app):
    """Setting 100% is a progress estimate, not completion — reaching it must
    leave the book on the shelf, and the page must explain why it is still there.
    """
    client = signed_in
    store = app.state.store
    book_id = store.add_book("Dune", book_category=BookCategory.FICTION)

    client.post(f"/books/{book_id}/progress", data={"percent_complete": "100", "started": "1"})

    assert store.get_item(book_id)["state"] == ItemState.BOOK
    body = client.get("/books").text
    assert "Dune" in body
    assert "move it to Done" in body


def test_restoring_a_finished_book_returns_it_to_its_shelf(store, books):
    """Undo must know what the item was. Books are not in user_lists(), so the
    generic restore would file a finished book as a next action."""
    store.complete(books[0])
    assert store.restore_book(books[0]) is True

    item = store.get_item(books[0])
    assert item["state"] == ItemState.BOOK
    assert item["completed_at"] is None
    assert "Dune" in [row["title"] for row in store.list_books()]


def test_a_restored_book_does_not_collide_with_a_live_rank(store):
    """A finished book keeps its old rank, which a later book may have reused.
    Restoring appends rather than reinstating a rank that is now taken."""
    first = store.add_book("first", book_category=BookCategory.FICTION)
    store.complete(first)
    second = store.add_book("second", book_category=BookCategory.FICTION)
    assert store.get_item(second)["rank"] == store.get_item(first)["rank"]

    store.restore_book(first)

    live = [row["rank"] for row in store.list_books()]
    assert len(set(live)) == len(live), f"duplicate ranks on the live shelf: {live}"
    assert [row["title"] for row in store.list_books()] == ["second", "first"]


def test_restore_route_sends_a_book_home_not_to_next_actions(signed_in, app):
    client = signed_in
    store = app.state.store
    book_id = store.add_book("Dune", book_category=BookCategory.FICTION)
    client.post(f"/books/{book_id}/finish")

    client.post(f"/items/{book_id}/restore", data={"back": "/list/done"})

    assert store.get_item(book_id)["state"] == ItemState.BOOK
    assert store.list_items(ItemState.NEXT_ACTION) == []


def test_restore_still_works_normally_for_non_books(store):
    """The book branch must not swallow ordinary restores."""
    item_id = store.capture("ordinary task")
    store.complete(item_id)

    assert store.restore_book(item_id) is False
    store.uncomplete(item_id)
    assert store.get_item(item_id)["state"] == ItemState.NEXT_ACTION


def test_category_float_is_transient(signed_in, app):
    """`top` reorders the page and nothing else — it must not be persisted."""
    client = signed_in
    store = app.state.store
    store.add_book("SICP", book_category=BookCategory.TECHNOLOGY)

    floated = client.get("/books?top=technology").text
    plain = client.get("/books").text

    assert floated.index("Technology") < floated.index("Fiction")
    assert plain.index("Fiction") < plain.index("Technology")

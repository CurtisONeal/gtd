"""The Today view and search.

Daily habits are a different kind of thing from tasks: swept several times a
day, and the question is "have I done it yet" — so what is already done matters
as much as what is not.
"""

from datetime import date

from gtd.models import ItemState

WEEKDAY_CODES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def make_daily(store, title, **rule):
    item_id = store.capture(title)
    store.set_state(item_id, ItemState.NEXT_ACTION)
    store.set_recurrence(item_id, **(rule or {"every": 1, "unit": "day"}))
    return item_id


def test_daily_shows_only_things_that_recur_today(store):
    make_daily(store, "meds")
    make_daily(store, "sunlight", days={WEEKDAY_CODES[date.today().weekday()]})
    make_daily(store, "weekly review", every=1, unit="week")
    store.set_state(store.capture("write the report"), ItemState.NEXT_ACTION)

    titles = [r["title"] for r in store.daily_items()["outstanding"]]

    assert "meds" in titles and "sunlight" in titles
    assert "weekly review" not in titles, "a weekly repeat is not a daily habit"
    assert "write the report" not in titles, "a one-off task is not a habit"


def test_completing_moves_it_to_done_today_not_out_of_sight(store):
    """The point of the view is 'have I done it yet', so completed ones stay."""
    meds = make_daily(store, "meds")
    store.complete(meds)

    buckets = store.daily_items()

    assert [r["title"] for r in buckets["outstanding"]] == []
    assert [r["title"] for r in buckets["done_today"]] == ["meds"]


def test_tomorrows_occurrence_does_not_show_today(store):
    """Completing spawns the next one deferred; it must not appear as still to do."""
    make_daily(store, "meds")
    store.complete(store.daily_items()["outstanding"][0]["id"])

    assert store.daily_items()["outstanding"] == []


def test_undoing_a_completion_does_not_leave_a_duplicate(store):
    """Completing spawns a successor. Undo must take it with it, or a mis-tick
    quietly doubles a daily habit."""
    meds = make_daily(store, "meds")
    successor = store.complete(meds)

    store.uncomplete(meds)

    live = store.list_items(ItemState.NEXT_ACTION, include_deferred=True)
    assert len(live) == 1
    assert live[0]["id"] == meds
    assert store.get_item(successor) is None


def test_undo_leaves_a_successor_that_was_already_acted_on(store):
    """If tomorrow's copy has itself been completed it is its own thing now."""
    meds = make_daily(store, "meds")
    successor = store.complete(meds)
    store.complete(successor)

    store.uncomplete(meds)

    assert store.get_item(successor) is not None


# ── Search ───────────────────────────────────────────────────────────────────


def test_search_matches_title_and_notes(store):
    store.set_state(store.capture("Email Dan"), ItemState.NEXT_ACTION)
    store.set_state(
        store.capture("Quarterly report", notes="ask Dan first"), ItemState.NEXT_ACTION
    )
    store.set_state(store.capture("unrelated"), ItemState.REFERENCE)

    assert len(store.search("dan")) == 2, "notes should be searched too"
    assert store.search("DAN"), "search should be case-insensitive"


def test_search_excludes_finished_unless_asked(store):
    store.complete(store.capture("an old thing"))

    assert store.search("old thing") == []
    assert len(store.search("old thing", include_finished=True)) == 1


def test_search_treats_wildcards_literally(store):
    """An unescaped % would match everything and look like a broken search."""
    store.set_state(store.capture("plain item"), ItemState.NEXT_ACTION)

    assert store.search("%") == []
    assert store.search("_") == []


def test_blank_search_returns_nothing_rather_than_everything(store):
    store.set_state(store.capture("something"), ItemState.NEXT_ACTION)

    assert store.search("") == []
    assert store.search("   ") == []


# ── Routes ───────────────────────────────────────────────────────────────────


def test_daily_page_separates_outstanding_from_done(signed_in, app):
    store = app.state.store
    make_daily(store, "meds")
    make_daily(store, "brush teeth")
    store.complete(store.daily_items()["outstanding"][0]["id"])

    body = signed_in.get("/daily").text

    assert "Still to do" in body and "Done today" in body
    assert "1 of 2 done" in body


def test_daily_page_explains_itself_when_empty(signed_in):
    body = signed_in.get("/daily").text

    assert "Nothing repeats daily yet" in body


def test_today_is_in_the_nav(signed_in):
    nav = signed_in.get("/daily").text.split("<nav>")[1].split("</nav>")[0]

    assert 'href="/daily"' in nav


def test_search_page_finds_a_recurring_item_to_edit(signed_in, app):
    """The stated reason for search: reach a repeating item to change it."""
    store = app.state.store
    make_daily(store, "take out the trash", days={"tue"})

    body = signed_in.get("/search?q=trash").text

    assert "take out the trash" in body
    assert "repeats every Tuesday" in body
    assert "/edit" in body, "results must be actionable, not just readable"


def test_search_with_no_query_just_shows_the_box(signed_in):
    body = signed_in.get("/search").text

    assert 'name="q"' in body
    assert "results for" not in body

"""The lists index, the collapsed nav, and finding repeating items.

The nav had grown to thirteen entries. What matters is that consolidating it
did not make anything unreachable.
"""

from gtd.models import ItemState


def test_every_list_is_reachable_from_the_lists_page(signed_in):
    """Nothing may become orphaned by shrinking the nav."""
    body = signed_in.get("/lists").text

    for href in (
        "/list/next_action", "/list/waiting_for", "/list/someday",
        "/list/reference", "/list/done", "/list/trashed",
        "/books", "/checklists", "/tech", "/projects",
    ):
        assert f'href="{href}"' in body, f"{href} is not linked from /lists"


def test_the_nav_is_short_and_keeps_the_inbox(signed_in):
    """Inbox stays out of the fold — it is the front door and carries the count
    that drives daily use."""
    body = signed_in.get("/lists").text
    nav = body.split("<nav>")[1].split("</nav>")[0]

    assert 'href="/inbox"' in nav
    assert 'href="/lists"' in nav
    # The long tail moved to the index page.
    for gone in ('href="/list/reference"', 'href="/books"', 'href="/list/trashed"'):
        assert gone not in nav, f"{gone} should no longer be in the nav"


def test_the_lists_page_shows_counts(signed_in, app):
    store = app.state.store
    store.set_state(store.capture("an action"), ItemState.NEXT_ACTION)
    store.set_state(store.capture("a note"), ItemState.REFERENCE)

    body = signed_in.get("/lists").text

    assert "Next Actions" in body and "Reference" in body


# ── Finding repeating items ──────────────────────────────────────────────────


def test_the_repeating_filter_narrows_the_list(signed_in, app):
    store = app.state.store
    repeating = store.capture("bins out")
    store.set_state(repeating, ItemState.NEXT_ACTION)
    store.set_recurrence(repeating, days={"wed"})
    store.set_state(store.capture("one-off thing"), ItemState.NEXT_ACTION)

    everything = signed_in.get("/list/next_action").text
    assert "bins out" in everything and "one-off thing" in everything

    filtered = signed_in.get("/list/next_action?repeating=1").text
    assert "bins out" in filtered
    assert "one-off thing" not in filtered


def test_the_repeating_filter_is_offered_and_escapable(signed_in, app):
    store = app.state.store
    store.set_state(store.capture("x"), ItemState.NEXT_ACTION)

    assert "Show only repeating items" in signed_in.get("/list/next_action").text
    filtered = signed_in.get("/list/next_action?repeating=1").text
    assert "Showing only items that repeat" in filtered
    assert 'href="/list/next_action"' in filtered, "must offer a way back"


def test_the_lists_page_links_to_repeating_items(signed_in):
    assert 'href="/list/next_action?repeating=1"' in signed_in.get("/lists").text


# ── Setting a repeat while clarifying ────────────────────────────────────────


def _defer(client, item_id, **extra):
    data = {"title": "take out the trash", "defer_until": "2026-09-08"}
    data.update(extra)
    return client.post(f"/inbox/{item_id}/defer", data=data, follow_redirects=False)


def test_clarifying_can_hand_off_to_the_repeat_settings(signed_in, app):
    """Deciding something recurs happens while processing the inbox, not later."""
    store = app.state.store
    item_id = store.capture("take out the trash")

    response = _defer(signed_in, item_id, then_repeat="1")

    assert response.status_code == 303
    assert response.headers["location"] == f"/items/{item_id}/edit?back=/inbox"
    assert store.get_item(item_id)["state"] == ItemState.NEXT_ACTION


def test_clarifying_without_the_box_continues_processing(signed_in, app):
    store = app.state.store
    item_id = store.capture("take out the trash")

    response = _defer(signed_in, item_id)

    assert response.headers["location"] == "/inbox"


def test_the_clarify_page_offers_the_repeat_handoff(signed_in, app):
    store = app.state.store
    store.capture("take out the trash")

    body = signed_in.get("/inbox?step=defer_form").text

    assert 'name="then_repeat"' in body


# ── The count and the page it links to must agree ────────────────────────────


def _repeating_next_action(store, title, *, defer_until=None):
    item_id = store.capture(title)
    store.set_state(store.capture("noise " + title), ItemState.NEXT_ACTION)
    store.set_state(item_id, ItemState.NEXT_ACTION, defer_until=defer_until)
    store.set_recurrence(item_id, every=1, unit="day")
    return item_id


def test_the_repeating_view_includes_deferred_occurrences(store, app=None):
    """Completing a daily item defers tomorrow's copy. The maintenance view must
    still show it — it is exactly the one you came to edit."""
    from datetime import date, timedelta

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    _repeating_next_action(store, "visible")
    _repeating_next_action(store, "deferred", defer_until=tomorrow)

    shown = store.list_items(
        ItemState.NEXT_ACTION, include_deferred=True, repeating=True
    )

    assert {r["title"] for r in shown} == {"visible", "deferred"}


def test_the_repeating_count_matches_what_the_page_shows(signed_in, app):
    """A count that promises more than its page delivers sends you hunting for
    something that was never going to be there."""
    from datetime import date, timedelta

    store = app.state.store
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    _repeating_next_action(store, "visible")
    _repeating_next_action(store, "deferred", defer_until=tomorrow)
    # A repeating item parked in Someday is live, but the page this count links
    # to only lists next actions. Counting it would over-promise.
    parked = store.capture("parked idea")
    store.set_state(parked, ItemState.SOMEDAY)
    store.set_recurrence(parked, every=1, unit="day")

    count = store.count_repeating()
    body = signed_in.get("/list/next_action?repeating=1").text
    shown = body.count('class="item-title"')

    assert count == 2
    assert shown == count, f"index says {count}, page shows {shown}"


def test_the_hidden_count_respects_the_active_filter(signed_in, app):
    """The tickler disclosure compared filtered items against the unfiltered
    list, so any filter made it claim the whole list was hidden."""
    from datetime import date, timedelta

    store = app.state.store
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    for n in range(5):
        store.set_state(store.capture(f"plain {n}"), ItemState.NEXT_ACTION)
    store.set_state(
        store.capture("deferred plain"), ItemState.NEXT_ACTION, defer_until=tomorrow
    )

    body = signed_in.get("/list/next_action").text

    # One genuinely deferred item — not "5 hidden" because five others exist.
    assert "1 hidden until their defer date" in body

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

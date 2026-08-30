import pytest
from fastapi.testclient import TestClient

from gtd.auth import hash_password
from gtd.config import Settings
from gtd.models import ItemState
from gtd.store import Store
from gtd.web import create_app

# `settings`, `app`, `client` and PASSWORD live in conftest.py so the books and
# web suites share one definition.
from conftest import PASSWORD  # noqa: F401


@pytest.fixture
def auth_client(client):
    resp = client.post(
        "/login", data={"username": "curtis", "password": PASSWORD}, follow_redirects=False
    )
    assert resp.status_code == 303
    return client


def store_of(client) -> Store:
    return client.app.state.store


# ── Auth ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path", ["/", "/inbox", "/list/next_action", "/projects"]
)
def test_pages_require_login(client, path):
    resp = client.get(path, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_page_is_public(client):
    assert client.get("/login").status_code == 200


def test_healthz_is_public(client):
    assert client.get("/healthz").json() == {"ok": True}


def test_wrong_password_rejected(client):
    resp = client.post("/login", data={"username": "curtis", "password": "wrong-password"})
    assert resp.status_code == 401
    assert "Incorrect username or password" in resp.text


def test_unknown_user_gets_identical_message(client):
    """Must not reveal whether the username exists."""
    resp = client.post("/login", data={"username": "nobody", "password": "whatever-long"})
    assert resp.status_code == 401
    assert "Incorrect username or password" in resp.text


def test_login_then_logout(auth_client):
    assert auth_client.get("/").status_code == 200
    auth_client.post("/logout", follow_redirects=False)
    assert auth_client.get("/", follow_redirects=False).status_code == 303


def test_rate_limit_locks_after_repeated_failures(client):
    for _ in range(5):
        client.post("/login", data={"username": "curtis", "password": "nope-nope-nope"})
    resp = client.post("/login", data={"username": "curtis", "password": PASSWORD})
    assert resp.status_code == 429
    assert "Too many attempts" in resp.text


# ── Capture ──────────────────────────────────────────────────────────────────

def test_capture_multiline_is_a_brain_dump(auth_client):
    auth_client.post("/capture", data={"text": "first thing\nsecond thing\n\nthird thing"})
    titles = {r["title"] for r in store_of(auth_client).list_items(ItemState.INBOX)}
    assert titles == {"first thing", "second thing", "third thing"}


def test_capture_redirects_so_refresh_does_not_duplicate(auth_client):
    resp = auth_client.post("/capture", data={"text": "once"}, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/"


# ── Clarify: the full decision tree ──────────────────────────────────────────

def test_clarify_shows_oldest_item_first(auth_client):
    store = store_of(auth_client)
    store.capture("oldest")
    store.capture("newest")
    assert "oldest" in auth_client.get("/inbox").text


def test_inbox_zero_message(auth_client):
    assert "Inbox zero" in auth_client.get("/inbox").text


@pytest.mark.parametrize(
    "target,expected",
    [
        ("reference", ItemState.REFERENCE),
        ("someday", ItemState.SOMEDAY),
        ("trashed", ItemState.TRASHED),
    ],
)
def test_non_actionable_paths(auth_client, target, expected):
    store = store_of(auth_client)
    item_id = store.capture("not actionable")
    auth_client.post(f"/inbox/{item_id}/file", data={"state": target})
    assert store.get_item(item_id)["state"] == expected


def test_file_rejects_a_state_outside_the_non_actionable_branch(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("x")
    auth_client.post(f"/inbox/{item_id}/file", data={"state": "next_action"})
    assert store.get_item(item_id)["state"] == ItemState.INBOX   # unchanged


def test_two_minute_rule_completes_it(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("quick thing")
    auth_client.post(f"/inbox/{item_id}/complete")
    item = store.get_item(item_id)
    assert item["state"] == ItemState.DONE and item["completed_at"] is not None


def test_defer_captures_full_metadata(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("raw capture")
    context_id = store.list_contexts()[0]["id"]

    auth_client.post(
        f"/inbox/{item_id}/defer",
        data={
            "title": "Refined next action",
            "context_id": str(context_id),
            "energy": "low",
            "time_estimate_min": "15",
            "priority": "2",
            "due_date": "2026-12-01",
            "defer_until": "",
        },
    )

    item = store.get_item(item_id)
    assert item["state"] == ItemState.NEXT_ACTION
    assert item["title"] == "Refined next action"
    assert item["context_id"] == context_id
    assert item["energy"] == "low"
    assert item["time_estimate_min"] == 15
    assert item["priority"] == 2
    assert item["due_date"] == "2026-12-01"
    assert item["defer_until"] is None      # empty string became NULL


def test_delegate_records_the_person(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("contract")
    auth_client.post(
        f"/inbox/{item_id}/delegate",
        data={"title": "Signed contract back", "waiting_on": "Dana", "due_date": ""},
    )
    item = store.get_item(item_id)
    assert item["state"] == ItemState.WAITING_FOR
    assert item["waiting_on"] == "Dana"


def test_project_creation_with_first_action(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("Redo the deck")
    area_id = store.list_areas()[0]["id"]

    auth_client.post(
        f"/inbox/{item_id}/project",
        data={
            "name": "Redo the deck",
            "outcome": "Deck usable by summer",
            "area_id": str(area_id),
            "first_action": "Price out lumber",
        },
    )

    projects = store.list_projects()
    assert len(projects) == 1
    assert projects[0]["outcome"] == "Deck usable by summer"
    assert projects[0]["open_actions"] == 1

    actions = store.list_items(ItemState.NEXT_ACTION, project_id=projects[0]["id"])
    assert [a["title"] for a in actions] == ["Price out lumber"]
    assert store.get_item(item_id) is None       # original consumed by the project


def test_project_without_first_action_is_stalled(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("Vague project")
    auth_client.post(
        f"/inbox/{item_id}/project",
        data={"name": "Vague project", "outcome": "", "area_id": "", "first_action": ""},
    )
    assert store.list_projects()[0]["open_actions"] == 0


def test_skip_moves_item_to_the_back(auth_client):
    store = store_of(auth_client)
    first = store.capture("first")
    store.capture("second")
    auth_client.post(f"/inbox/{first}/skip")
    assert store.next_inbox_item()["title"] == "second"


# ── Lists ────────────────────────────────────────────────────────────────────

def test_list_pages_render_for_every_user_list(auth_client):
    for state in ItemState.user_lists():
        assert auth_client.get(f"/list/{state}").status_code == 200


def test_unknown_list_redirects_home(auth_client):
    resp = auth_client.get("/list/nonsense", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/"


def test_complete_and_delete_from_list(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("do it")
    store.set_state(item_id, ItemState.NEXT_ACTION)

    auth_client.post(f"/items/{item_id}/complete", data={"back": "/list/next_action"})
    assert store.get_item(item_id)["state"] == ItemState.DONE

    other = store.capture("delete me")
    store.set_state(other, ItemState.NEXT_ACTION)
    auth_client.post(f"/items/{other}/delete", data={"back": "/list/next_action"})
    assert store.get_item(other)["state"] == ItemState.TRASHED


def test_open_redirect_is_refused(auth_client):
    """A `back` pointing off-site must not be followed."""
    store = store_of(auth_client)
    item_id = store.capture("x")
    store.set_state(item_id, ItemState.NEXT_ACTION)
    resp = auth_client.post(
        f"/items/{item_id}/complete",
        data={"back": "https://evil.example.com/"},
        follow_redirects=False,
    )
    assert resp.headers["location"] == "/list/next_action"


def test_deferred_items_hidden_but_counted(auth_client):
    from datetime import date, timedelta

    store = store_of(auth_client)
    item_id = store.capture("later")
    store.set_state(
        item_id,
        ItemState.NEXT_ACTION,
        defer_until=(date.today() + timedelta(days=10)).isoformat(),
    )

    page = auth_client.get("/list/next_action").text
    assert "later" not in page
    assert "hidden until their defer date" in page

    assert "later" in auth_client.get("/list/next_action?deferred=1").text


# ── Projects page ────────────────────────────────────────────────────────────

def test_create_project_and_add_action(auth_client):
    store = store_of(auth_client)
    auth_client.post("/projects", data={"name": "Website", "outcome": "Live", "area_id": ""})
    project_id = store.list_projects()[0]["id"]

    auth_client.post(
        f"/projects/{project_id}/actions", data={"title": "Write copy", "context_id": ""}
    )
    actions = store.list_items(ItemState.NEXT_ACTION, project_id=project_id)
    assert [a["title"] for a in actions] == ["Write copy"]

    auth_client.post(f"/projects/{project_id}/complete")
    assert store.list_projects() == []


# ── Capture API (for the later Discord/email surfaces) ───────────────────────

def test_capture_api_requires_the_token(client):
    resp = client.post("/api/capture", json={"title": "x"})
    assert resp.status_code == 401


def test_capture_api_accepts_a_valid_token(client):
    resp = client.post(
        "/api/capture",
        json={"title": "from the bot", "source": "discord"},
        headers={"Authorization": "Bearer test-capture-token"},
    )
    assert resp.status_code == 201

    item = store_of(client).list_items(ItemState.INBOX)[0]
    assert item["title"] == "from the bot"
    assert item["source"] == "discord"


def test_capture_api_rejects_empty_title(client):
    resp = client.post(
        "/api/capture", json={"title": "   "}, headers={"Authorization": "Bearer test-capture-token"}
    )
    assert resp.status_code == 400


def test_capture_api_disabled_without_a_configured_token(settings, tmp_path):
    from dataclasses import replace

    app = create_app(replace(settings, capture_token=None, db_path=tmp_path / "off.db"))
    resp = TestClient(app).post("/api/capture", json={"title": "x"})
    assert resp.status_code == 404


# ── Export ───────────────────────────────────────────────────────────────────

def test_export_writes_files(auth_client, settings):
    store_of(auth_client).capture("something to export")
    auth_client.post("/export")
    assert (settings.export_dir / "inbox.md").exists()
    assert "something to export" in (settings.export_dir / "inbox.md").read_text()


# ── Edit & undo (added after live use surfaced the gap) ──────────────────────

def test_edit_form_renders_with_current_values(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("Mispelled titel")
    store.set_state(item_id, ItemState.NEXT_ACTION)

    page = auth_client.get(f"/items/{item_id}/edit").text
    assert "Mispelled titel" in page
    assert "Edit" in page


def test_edit_fixes_a_typo(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("Call the dentst")
    store.set_state(item_id, ItemState.NEXT_ACTION)

    auth_client.post(
        f"/items/{item_id}/edit",
        data={"title": "Call the dentist", "notes": "", "state": "next_action",
              "back": "/list/next_action"},
    )
    assert store.get_item(item_id)["title"] == "Call the dentist"


def test_edit_with_blank_notes_does_not_violate_not_null(auth_client):
    """Empty optional text must stay '' on NOT NULL columns, not become NULL."""
    store = store_of(auth_client)
    item_id = store.capture("thing")
    resp = auth_client.post(
        f"/items/{item_id}/edit",
        data={"title": "thing", "notes": "", "state": "inbox", "back": "/"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert store.get_item(item_id)["notes"] == ""


def test_edit_can_move_an_item_between_lists(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("maybe later")
    store.set_state(item_id, ItemState.NEXT_ACTION)

    auth_client.post(
        f"/items/{item_id}/edit",
        data={"title": "maybe later", "notes": "", "state": "someday", "back": "/"},
    )
    assert store.get_item(item_id)["state"] == ItemState.SOMEDAY


def test_edit_clears_optional_fields_back_to_null(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("x")
    store.set_state(item_id, ItemState.NEXT_ACTION, due_date="2026-01-01", priority=1)

    auth_client.post(
        f"/items/{item_id}/edit",
        data={"title": "x", "notes": "", "state": "next_action",
              "due_date": "", "priority": "", "back": "/"},
    )
    item = store.get_item(item_id)
    assert item["due_date"] is None and item["priority"] is None


def test_edit_rejects_a_blank_title(store):
    item_id = store.capture("has a title")
    with pytest.raises(ValueError, match="title cannot be empty"):
        store.update_item(item_id, title="   ")


def test_undo_a_completion(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("done too soon")
    store.set_state(item_id, ItemState.NEXT_ACTION)
    store.complete(item_id)

    auth_client.post(f"/items/{item_id}/restore", data={"back": "/list/done"})
    item = store.get_item(item_id)
    assert item["state"] == ItemState.NEXT_ACTION
    assert item["completed_at"] is None


def test_undo_a_delete(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("deleted by mistake")
    store.delete_item(item_id)
    assert store.get_item(item_id)["state"] == ItemState.TRASHED

    auth_client.post(f"/items/{item_id}/restore", data={"back": "/list/trashed"})
    assert store.get_item(item_id)["state"] == ItemState.NEXT_ACTION


def test_restore_can_target_a_specific_list(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("reference material")
    store.set_state(item_id, ItemState.REFERENCE)
    store.delete_item(item_id)

    auth_client.post(
        f"/items/{item_id}/restore", data={"back": "/list/trashed", "state": "reference"}
    )
    assert store.get_item(item_id)["state"] == ItemState.REFERENCE


def test_restore_ignores_a_bogus_target_state(auth_client):
    store = store_of(auth_client)
    item_id = store.capture("x")
    store.delete_item(item_id)
    auth_client.post(f"/items/{item_id}/restore", data={"state": "nonsense", "back": "/"})
    assert store.get_item(item_id)["state"] == ItemState.NEXT_ACTION


def test_done_and_trash_pages_render(auth_client):
    store = store_of(auth_client)
    done_id = store.capture("finished")
    store.complete(done_id)
    trashed_id = store.capture("binned")
    store.delete_item(trashed_id)

    assert "finished" in auth_client.get("/list/done").text
    assert "binned" in auth_client.get("/list/trashed").text


def test_edit_form_for_a_missing_item_redirects(auth_client):
    resp = auth_client.get("/items/99999/edit", follow_redirects=False)
    assert resp.status_code == 303


def test_time_estimate_options_are_sane(auth_client):
    """Regression: min=1 step=5 on a number input produced 1, 6, 11, 16..."""
    from gtd.models import TIME_ESTIMATES

    store = store_of(auth_client)
    store.capture("something")
    page = auth_client.get("/inbox?step=defer_form").text

    assert 'type="number"' not in page          # no stepper at all any more
    for minutes, label in TIME_ESTIMATES:
        assert f'value="{minutes}"' in page and label in page
    assert [m for m, _ in TIME_ESTIMATES] == sorted(m for m, _ in TIME_ESTIMATES)


# ── Direct-add to a list (inbox-bypass) ──────────────────────────────────────

@pytest.mark.parametrize(
    "state", ["next_action", "waiting_for", "someday", "reference"]
)
def test_direct_add_reaches_every_addable_list(auth_client, state):
    """Before this existed, waiting_for/someday/reference were only reachable by
    processing an inbox item — impossible at inbox zero."""
    store = store_of(auth_client)
    resp = auth_client.post(
        f"/list/{state}/add", data={"title": f"direct into {state}"}, follow_redirects=False
    )
    assert resp.status_code == 303 and resp.headers["location"] == f"/list/{state}"

    items = store.list_items(state)
    assert [i["title"] for i in items] == [f"direct into {state}"]
    assert store.counts_by_state()[ItemState.INBOX] == 0     # never touched the inbox


def test_direct_add_waiting_for_captures_the_person(auth_client):
    store = store_of(auth_client)
    auth_client.post(
        "/list/waiting_for/add",
        data={"title": "the signed lease", "waiting_on": "Dana", "due_date": "2026-09-01"},
    )
    item = store.list_items(ItemState.WAITING_FOR)[0]
    assert item["waiting_on"] == "Dana"
    assert item["due_date"] == "2026-09-01"


def test_direct_add_waiting_for_can_be_blocked_by_a_task(auth_client):
    store = store_of(auth_client)
    blocker = store.capture("Buy cookies")
    store.set_state(blocker, ItemState.NEXT_ACTION)

    auth_client.post(
        "/list/waiting_for/add",
        data={"title": "Eat cookies", "blocking_item_id": str(blocker)},
    )

    item = store.list_items(ItemState.WAITING_FOR)[0]
    assert item["title"] == "Eat cookies"
    assert item["blocked_by_titles"] == "Buy cookies"


def test_waiting_page_distinguishes_task_blockers_from_people(auth_client):
    store = store_of(auth_client)
    blocker = store.capture("Buy cookies")
    blocked = store.capture("Eat cookies")
    store.set_state(blocker, ItemState.NEXT_ACTION)
    store.set_state(blocked, ItemState.WAITING_FOR, waiting_on="Dana")
    store.add_dependency(blocked, blocker)

    page = auth_client.get("/list/waiting_for").text
    assert "blocked by Buy cookies" in page
    assert "waiting on Dana" in page


def test_waiting_page_calls_out_task_unblocking(auth_client):
    page = auth_client.get("/list/waiting_for").text
    assert "Task blockers return to Next Actions when completed" in page
    assert "Use Waiting on for people or external events" in page


def test_completing_blocker_promotes_waiting_item(auth_client):
    store = store_of(auth_client)
    blocker = store.capture("Buy cookies")
    blocked = store.capture("Eat cookies")
    store.set_state(blocker, ItemState.NEXT_ACTION)
    store.set_state(blocked, ItemState.WAITING_FOR)
    store.add_dependency(blocked, blocker)

    auth_client.post(f"/items/{blocker}/complete", data={"back": "/list/next_action"})

    assert store.get_item(blocked)["state"] == ItemState.NEXT_ACTION


def test_edit_can_assign_a_blocking_task(auth_client):
    store = store_of(auth_client)
    blocker = store.capture("Buy cookies")
    blocked = store.capture("Eat cookies")
    store.set_state(blocker, ItemState.NEXT_ACTION)
    store.set_state(blocked, ItemState.NEXT_ACTION)

    auth_client.post(
        f"/items/{blocked}/edit",
        data={
            "title": "Eat cookies",
            "notes": "",
            "state": "waiting_for",
            "blocking_item_id": str(blocker),
            "back": "/list/next_action",
        },
    )

    item = store.list_items(ItemState.WAITING_FOR)[0]
    assert item["title"] == "Eat cookies"
    assert item["blocked_by_titles"] == "Buy cookies"


def test_direct_add_next_action_takes_a_context(auth_client):
    store = store_of(auth_client)
    context_id = store.list_contexts()[0]["id"]
    auth_client.post(
        "/list/next_action/add",
        data={"title": "call the bank", "context_id": str(context_id)},
    )
    assert store.list_items(ItemState.NEXT_ACTION)[0]["context_id"] == context_id


def test_direct_add_reference_keeps_notes(auth_client):
    store = store_of(auth_client)
    auth_client.post(
        "/list/reference/add",
        data={"title": "wifi password", "notes": "in the drawer"},
    )
    assert store.list_items(ItemState.REFERENCE)[0]["notes"] == "in the drawer"


@pytest.mark.parametrize("state", ["done", "trashed", "inbox", "nonsense"])
def test_direct_add_refused_for_non_addable_states(auth_client, state):
    """done/trashed are outcomes, and inbox already has the capture box."""
    store = store_of(auth_client)
    resp = auth_client.post(
        f"/list/{state}/add", data={"title": "nope"}, follow_redirects=False
    )
    assert resp.headers["location"] == "/"
    assert sum(store.counts_by_state().values()) == 0


def test_add_form_appears_on_the_lists_that_need_it(auth_client):
    for state in ("next_action", "waiting_for", "someday", "reference"):
        assert "Add directly to" in auth_client.get(f"/list/{state}").text
    for state in ("done", "trashed"):
        assert "Add directly to" not in auth_client.get(f"/list/{state}").text


# ── Local-only enforcement (ADR-010) ─────────────────────────────────────────

def _local_only_app(settings, tmp_path):
    from dataclasses import replace
    return create_app(replace(settings, local_only=True, db_path=tmp_path / "lo.db"))


def test_loopback_predicate():
    from gtd.web import _is_loopback
    assert _is_loopback("127.0.0.1")
    assert _is_loopback("127.1.2.3")      # all of 127/8, not just .1
    assert _is_loopback("::1")
    assert _is_loopback("localhost")
    assert not _is_loopback("0.0.0.0")
    assert not _is_loopback("100.82.195.54")   # a tailnet address is NOT local
    assert not _is_loopback("192.168.86.30")   # nor is the LAN
    assert not _is_loopback(None)
    assert not _is_loopback("evil.example.com")


def test_local_only_allows_loopback_callers(settings, tmp_path):
    """A caller on this machine is unaffected.

    Note TestClient defaults its peer address to the literal string
    "testclient", not an IP — so a loopback address has to be set explicitly.
    `_is_loopback` deliberately does NOT whitelist that string: weakening the
    production check to satisfy a test harness would defeat the point.
    """
    app = _local_only_app(settings, tmp_path)
    app.state.store.upsert_user("curtis", hash_password(PASSWORD))
    local = TestClient(app, client=("127.0.0.1", 51000))
    assert local.get("/login").status_code == 200

    v6 = TestClient(app, client=("::1", 51001))
    assert v6.get("/login").status_code == 200


def test_local_only_rejects_remote_callers(settings, tmp_path):
    app = _local_only_app(settings, tmp_path)
    # client=... sets the peer address TestClient reports.
    remote = TestClient(app, client=("100.82.195.54", 51234))
    resp = remote.get("/login")
    assert resp.status_code == 403
    assert "local-only" in resp.text


def test_local_only_rejects_remote_before_auth_or_session(settings, tmp_path):
    """The guard is outermost: a remote caller cannot even reach the login POST,
    so it can't consume rate-limit budget or touch the session."""
    app = _local_only_app(settings, tmp_path)
    app.state.store.upsert_user("curtis", hash_password(PASSWORD))
    remote = TestClient(app, client=("10.0.0.9", 4444))

    for path, method in (("/", "get"), ("/healthz", "get"), ("/inbox", "get")):
        assert getattr(remote, method)(path).status_code == 403

    resp = remote.post("/login", data={"username": "curtis", "password": PASSWORD})
    assert resp.status_code == 403
    assert "set-cookie" not in {k.lower() for k in resp.headers}


def test_local_only_off_by_default_permits_remote(settings, tmp_path):
    """Personal instances on a tailnet must keep working — this is opt-in."""
    from dataclasses import replace
    app = create_app(replace(settings, local_only=False, db_path=tmp_path / "open.db"))
    remote = TestClient(app, client=("100.82.195.54", 51234))
    assert remote.get("/login").status_code == 200


def test_effective_host_overrides_configured_host_when_local_only():
    from dataclasses import replace
    from gtd.config import Settings
    from pathlib import Path as _P

    base = Settings(
        db_path=_P("x.db"), export_dir=_P("e"), session_secret="s",
        secure_cookies=False, session_max_age=1, capture_token=None,
        local_only=False, host="0.0.0.0", port=8765,
    )
    assert base.effective_host == "0.0.0.0"
    assert replace(base, local_only=True).effective_host == "127.0.0.1"

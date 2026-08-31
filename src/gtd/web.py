"""FastAPI application.

Server-rendered forms with POST-redirect-GET. No JavaScript dependencies at
all: the clarify flow is a sequence of plain page loads, which means it works
with JS disabled, the back button behaves, and refreshing never re-submits.
"""

from __future__ import annotations

import ipaddress
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .auth import SESSION_USER_KEY, LoginRateLimiter, verify_password
from .config import Settings, load_settings
from .db import Database
from .export import export_all
from .models import (
    BOOK_CATEGORY_LABELS,
    PERCENT_BUCKETS,
    STATE_LABELS,
    TIME_ESTIMATES,
    BookCategory,
    ItemState,
    Source,
)
from .store import Store

HERE = Path(__file__).resolve().parent

# Paths reachable without a session.
PUBLIC_PATHS = {"/login", "/static", "/healthz", "/api/capture"}


def _int_or_none(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _safe_back(value: str | None, default: str) -> str:
    """Only ever redirect to a local path — never to an attacker-supplied host."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return default
    return value


def _is_loopback(host: str | None) -> bool:
    """True only for addresses on this machine.

    Uses the real peer address from the socket, never a forwarded header — those
    are attacker-controlled and would defeat the point.
    """
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # A UNIX socket or a hostname rather than an IP. "localhost" resolves
        # here; anything else is not something we can vouch for.
        return host in {"localhost", "::1"}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    db = Database(settings.db_path)
    db.init_schema()
    store = Store(db)

    app = FastAPI(title="GTD", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.store = store
    app.state.limiter = LoginRateLimiter()

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=str(HERE / "templates"))

    # ── Auth gate ────────────────────────────────────────────────────────────

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        """One gate for every route — safer than remembering a decorator."""
        path = request.url.path
        is_public = any(path == p or path.startswith(p + "/") for p in PUBLIC_PATHS)
        if not is_public and not request.session.get(SESSION_USER_KEY):
            return RedirectResponse("/login", status_code=303)
        return await call_next(request)

    # Added AFTER the gate on purpose: Starlette applies middleware in reverse
    # order of registration, so the last one added is the outermost. Session
    # handling must wrap the auth gate, or request.session won't exist yet.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        max_age=settings.session_max_age,
        same_site="lax",       # blocks cookies on cross-site POST — our CSRF defense
        https_only=settings.secure_cookies,
    )

    # Registered last, so it is the OUTERMOST middleware and runs before session
    # parsing or auth. This is the structural half of the local-only guarantee:
    # `gtd serve` refuses to bind a public interface, but someone can always
    # invoke uvicorn directly with --host 0.0.0.0. This check does not care what
    # was bound — it rejects any request whose peer is not on this machine, so
    # the constraint holds regardless of how the process was started.
    if settings.local_only:
        @app.middleware("http")
        async def local_only_guard(request: Request, call_next):
            if not _is_loopback(request.client.host if request.client else None):
                return PlainTextResponse(
                    "This instance is configured local-only (GTD_LOCAL_ONLY=true) "
                    "and serves requests from this machine only.",
                    status_code=403,
                )
            return await call_next(request)

    def render(request: Request, template: str, **ctx: Any) -> HTMLResponse:
        """Every page gets the nav counts and today's date."""
        base = {
            "request": request,
            "user": request.session.get(SESSION_USER_KEY),
            "counts": store.counts_by_state(),
            "today": date.today().isoformat(),
        }
        base.update(ctx)
        return templates.TemplateResponse(request, template, base)

    # ── Login ────────────────────────────────────────────────────────────────

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request):
        if request.session.get(SESSION_USER_KEY):
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(
            request, "login.html", {"request": request, "no_user": store.user_count() == 0}
        )

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...)):
        client = request.client.host if request.client else "unknown"
        limiter: LoginRateLimiter = app.state.limiter

        if limiter.is_locked(client):
            wait = max(1, limiter.seconds_remaining(client) // 60)
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "request": request,
                    "error": f"Too many attempts. Try again in about {wait} minute(s).",
                    "username": username,
                },
                status_code=429,
            )

        user = store.get_user(username)
        if user and verify_password(user["password_hash"], password):
            limiter.reset(client)
            request.session[SESSION_USER_KEY] = user["username"]
            return RedirectResponse("/", status_code=303)

        limiter.record_failure(client)
        # Deliberately identical message whether the user exists or not.
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "error": "Incorrect username or password.",
                "username": username,
                "no_user": store.user_count() == 0,
            },
            status_code=401,
        )

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # ── Capture ──────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        projects = store.list_projects()
        return render(
            request,
            "index.html",
            due_soon=store.due_soon(),
            project_count=len(projects),
            stalled_projects=[
                p for p in projects
                if p["open_actions"] == 0 and p["waiting_items"] == 0
            ],
        )

    @app.post("/capture")
    def capture(request: Request, text: str = Form(...)):
        """One item per line, so a brain dump is a single paste."""
        store.capture_many(text.splitlines(), source=Source.WEB)
        return RedirectResponse("/", status_code=303)

    @app.post("/api/capture")
    async def api_capture(request: Request):
        """Token-authed capture for other surfaces (Discord bot, email poller,
        shortcuts). Disabled unless GTD_CAPTURE_TOKEN is set."""
        if not settings.capture_api_enabled:
            return JSONResponse({"error": "capture api disabled"}, status_code=404)

        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else ""
        if token != settings.capture_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        payload = await request.json()
        title = str(payload.get("title", "")).strip()
        if not title:
            return JSONResponse({"error": "title required"}, status_code=400)

        item_id = store.capture(
            title,
            notes=str(payload.get("notes", "")),
            source=str(payload.get("source", Source.API)),
        )
        return JSONResponse({"id": item_id, "title": title}, status_code=201)

    # ── Clarify ──────────────────────────────────────────────────────────────

    @app.get("/inbox", response_class=HTMLResponse)
    def inbox(request: Request, step: str = "actionable"):
        item = store.next_inbox_item()
        return render(
            request,
            "clarify.html",
            item=item,
            step=step,
            remaining=store.counts_by_state().get(str(ItemState.INBOX), 0),
            contexts=store.list_contexts(),
            areas=store.list_areas(),
            projects=store.list_projects(),
            time_estimates=TIME_ESTIMATES,
        )

    @app.post("/inbox/{item_id}/file")
    def inbox_file(item_id: int, state: str = Form(...)):
        """Non-actionable: reference, someday, or trash."""
        allowed = {ItemState.REFERENCE, ItemState.SOMEDAY, ItemState.TRASHED}
        if state not in {str(s) for s in allowed}:
            return RedirectResponse("/inbox", status_code=303)
        store.set_state(item_id, state)
        return RedirectResponse("/inbox", status_code=303)

    @app.post("/inbox/{item_id}/complete")
    def inbox_complete(item_id: int):
        """The two-minute rule — did it on the spot."""
        store.complete(item_id)
        return RedirectResponse("/inbox", status_code=303)

    @app.post("/inbox/{item_id}/skip")
    def inbox_skip(item_id: int):
        store.send_to_back_of_inbox(item_id)
        return RedirectResponse("/inbox", status_code=303)

    @app.post("/inbox/{item_id}/defer")
    def inbox_defer(
        item_id: int,
        title: str = Form(...),
        context_id: str = Form(""),
        energy: str = Form(""),
        time_estimate_min: str = Form(""),
        priority: str = Form(""),
        project_id: str = Form(""),
        area_id: str = Form(""),
        due_date: str = Form(""),
        defer_until: str = Form(""),
    ):
        store.set_state(
            item_id,
            ItemState.NEXT_ACTION,
            title=title,
            context_id=_int_or_none(context_id),
            energy=_str_or_none(energy),
            time_estimate_min=_int_or_none(time_estimate_min),
            priority=_int_or_none(priority),
            project_id=_int_or_none(project_id),
            area_id=_int_or_none(area_id),
            due_date=_str_or_none(due_date),
            defer_until=_str_or_none(defer_until),
        )
        return RedirectResponse("/inbox", status_code=303)

    @app.post("/inbox/{item_id}/delegate")
    def inbox_delegate(
        item_id: int,
        title: str = Form(...),
        waiting_on: str = Form(...),
        due_date: str = Form(""),
    ):
        store.set_state(
            item_id,
            ItemState.WAITING_FOR,
            title=title,
            waiting_on=waiting_on,
            due_date=_str_or_none(due_date),
        )
        return RedirectResponse("/inbox", status_code=303)

    @app.post("/inbox/{item_id}/project")
    def inbox_project(
        item_id: int,
        name: str = Form(...),
        outcome: str = Form(""),
        area_id: str = Form(""),
        first_action: str = Form(""),
    ):
        """The captured item becomes the project itself. Its first next action is
        captured separately — a project is an outcome, not an action."""
        area = _int_or_none(area_id)
        project_id = store.create_project(name, outcome=outcome, area_id=area)

        first_action = first_action.strip()
        if first_action:
            action_id = store.capture(first_action, source=Source.WEB)
            store.set_state(
                action_id, ItemState.NEXT_ACTION, project_id=project_id, area_id=area
            )

        # The original inbox item's content now lives in the project record.
        store.delete_item(item_id, hard=True)
        return RedirectResponse("/inbox", status_code=303)

    # ── Lists ────────────────────────────────────────────────────────────────

    # ── Books ────────────────────────────────────────────────────────────────

    @app.get("/books", response_class=HTMLResponse)
    def books(request: Request, top: str = ""):
        """The reading page: books grouped by category, ranked within each.

        `top` floats one category to the front. That ordering is deliberately
        transient — a way to say "I want to work on this shelf now", not a
        preference worth storing. Nothing about it is persisted.
        """
        by_category: dict[str, list[Any]] = {str(c): [] for c in BookCategory}
        for book in store.list_books():
            by_category.setdefault(book["book_category"] or "", []).append(book)

        order = [str(c) for c in BookCategory]
        if top in order:
            order.remove(top)
            order.insert(0, top)

        return render(
            request,
            "books.html",
            categories=order,
            category_labels=BOOK_CATEGORY_LABELS,
            books_by_category=by_category,
            percent_buckets=PERCENT_BUCKETS,
            top=top,
        )

    @app.post("/books/add")
    def books_add(
        title: str = Form(...),
        book_category: str = Form(...),
        is_audio: str = Form(""),
        started: str = Form(""),
    ):
        if book_category not in {str(c) for c in BookCategory}:
            return RedirectResponse("/books", status_code=303)
        store.add_book(
            title,
            book_category=book_category,
            is_audio=bool(is_audio),
            started=bool(started),
        )
        return RedirectResponse("/books", status_code=303)

    @app.post("/books/{item_id}/move")
    def books_move(item_id: int, delta: int = Form(...), top: str = Form("")):
        """Reorder within the book's own category — each shelf orders alone."""
        if delta in (-1, 1):
            store.move_in_order(item_id, delta, group="book_category")
        suffix = f"?top={top}" if top else ""
        return RedirectResponse(f"/books{suffix}", status_code=303)

    @app.post("/books/{item_id}/progress")
    def books_progress(
        item_id: int,
        percent_complete: str = Form(""),
        started: str = Form(""),
        is_audio: str = Form(""),
        top: str = Form(""),
    ):
        percent = _int_or_none(percent_complete)
        if percent is not None and percent not in PERCENT_BUCKETS:
            percent = None
        store.set_book_progress(
            item_id,
            percent_complete=percent,
            started=bool(started),
            is_audio=bool(is_audio),
        )
        suffix = f"?top={top}" if top else ""
        return RedirectResponse(f"/books{suffix}", status_code=303)

    @app.post("/books/{item_id}/finish")
    def books_finish(item_id: int):
        """Finishing a book completes it like anything else, so it leaves the
        reading page rather than lingering at 100%."""
        store.update_item(item_id, percent_complete=100)
        store.complete(item_id)
        return RedirectResponse("/books", status_code=303)

    # ── Checklists ───────────────────────────────────────────────────────────

    @app.get("/checklists", response_class=HTMLResponse)
    def checklists(request: Request, show_done: int = 0):
        return render(
            request,
            "checklists.html",
            checklists=store.list_checklists(),
            finished=store.list_checklists(status="done") if show_done else [],
            show_done=bool(show_done),
        )

    @app.post("/checklists")
    def checklists_create(name: str = Form(...), evergreen: str = Form("")):
        if not name.strip():
            return RedirectResponse("/checklists", status_code=303)
        checklist_id = store.create_checklist(name, evergreen=bool(evergreen))
        return RedirectResponse(f"/checklists/{checklist_id}", status_code=303)

    @app.get("/checklists/{checklist_id}", response_class=HTMLResponse)
    def checklist_detail(request: Request, checklist_id: int):
        checklist = store.get_checklist(checklist_id)
        if checklist is None:
            return RedirectResponse("/checklists", status_code=303)
        items = store.list_checklist_items(checklist_id)
        return render(
            request,
            "checklist.html",
            checklist=checklist,
            items=items,
            all_ticked=bool(items) and all(i["ticked"] for i in items),
        )

    @app.post("/checklists/{checklist_id}/items")
    def checklist_add_item(checklist_id: int, title: str = Form(...)):
        if title.strip():
            store.add_checklist_item(checklist_id, title)
        return RedirectResponse(f"/checklists/{checklist_id}", status_code=303)

    @app.post("/checklists/{checklist_id}/items/{item_id}/tick")
    def checklist_tick(checklist_id: int, item_id: int, ticked: str = Form("")):
        store.set_ticked(item_id, bool(ticked))
        return RedirectResponse(f"/checklists/{checklist_id}", status_code=303)

    @app.post("/checklists/{checklist_id}/items/{item_id}/move")
    def checklist_move(checklist_id: int, item_id: int, delta: int = Form(...)):
        if delta in (-1, 1):
            store.move_in_order(item_id, delta, group="checklist_id")
        return RedirectResponse(f"/checklists/{checklist_id}", status_code=303)

    @app.post("/checklists/{checklist_id}/reset")
    def checklist_reset(checklist_id: int):
        """Evergreen only — clears ticks so the list can be run again."""
        store.reset_checklist(checklist_id)
        return RedirectResponse(f"/checklists/{checklist_id}", status_code=303)

    @app.post("/checklists/{checklist_id}/complete")
    def checklist_complete(checklist_id: int):
        """One-off only. Completion is manual even when everything is ticked."""
        store.complete_checklist(checklist_id)
        return RedirectResponse("/checklists", status_code=303)

    @app.post("/checklists/{checklist_id}/reopen")
    def checklist_reopen(checklist_id: int):
        store.reopen_checklist(checklist_id)
        return RedirectResponse(f"/checklists/{checklist_id}", status_code=303)

    @app.post("/checklists/{checklist_id}/delete")
    def checklist_delete(checklist_id: int):
        store.delete_checklist(checklist_id)
        return RedirectResponse("/checklists", status_code=303)

    @app.get("/list/{state}", response_class=HTMLResponse)
    def list_state(
        request: Request,
        state: str,
        deferred: int = 0,
        context_id: str = "",
        area_id: str = "",
    ):
        # Ordered lists are ranked and grouped; the generic list page can show
        # neither, so send each to the page that can.
        ordered_pages = {
            str(ItemState.BOOK): "/books",
            str(ItemState.CHECKLIST): "/checklists",
        }
        if state in ordered_pages:
            return RedirectResponse(ordered_pages[state], status_code=303)
        if state not in {str(s) for s in ItemState}:
            return RedirectResponse("/", status_code=303)

        ctx_id = _int_or_none(context_id)
        ar_id = _int_or_none(area_id)

        items = store.list_items(
            state, include_deferred=bool(deferred), context_id=ctx_id, area_id=ar_id
        )
        # How many are being withheld by the tickler, so it's visible not silent.
        hidden = 0
        if state == ItemState.NEXT_ACTION and not deferred:
            hidden = len(
                store.list_items(state, include_deferred=True, context_id=ctx_id, area_id=ar_id)
            ) - len(items)

        return render(
            request,
            "list.html",
            state=state,
            label=STATE_LABELS.get(state, state),
            items=items,
            hidden_deferred=hidden,
            contexts=store.list_contexts(),
            areas=store.list_areas(),
            selected_context=ctx_id,
            selected_area=ar_id,
            blocker_candidates=store.list_dependency_candidates(),
            back=str(request.url.path),
        )

    @app.post("/list/{state}/add")
    def list_add(
        state: str,
        title: str = Form(...),
        notes: str = Form(""),
        waiting_on: str = Form(""),
        blocking_item_id: str = Form(""),
        context_id: str = Form(""),
        due_date: str = Form(""),
    ):
        """Add straight to a list, skipping capture-then-clarify.

        Capture-first is the discipline, but when you already know something is
        a waiting-for or a reference note, routing it through the inbox is
        friction with no payoff — and if the inbox is empty there was
        previously no way into these lists at all.
        """
        addable = {
            ItemState.NEXT_ACTION,
            ItemState.WAITING_FOR,
            ItemState.SOMEDAY,
            ItemState.REFERENCE,
        }
        if state not in {str(s) for s in addable}:
            return RedirectResponse("/", status_code=303)

        item_id = store.capture(title, notes=notes, source=Source.WEB)
        store.set_state(
            item_id,
            state,
            waiting_on=_str_or_none(waiting_on),
            context_id=_int_or_none(context_id),
            due_date=_str_or_none(due_date),
        )
        blocker = _int_or_none(blocking_item_id)
        if state == ItemState.WAITING_FOR and blocker is not None:
            store.replace_dependencies(item_id, [blocker])
        return RedirectResponse(f"/list/{state}", status_code=303)

    @app.post("/items/{item_id}/complete")
    def item_complete(item_id: int, back: str = Form("/list/next_action")):
        store.complete(item_id)
        return RedirectResponse(_safe_back(back, "/list/next_action"), status_code=303)

    @app.post("/items/{item_id}/delete")
    def item_delete(item_id: int, back: str = Form("/list/next_action")):
        store.delete_item(item_id)
        return RedirectResponse(_safe_back(back, "/list/next_action"), status_code=303)

    @app.post("/items/{item_id}/restore")
    def item_restore(item_id: int, back: str = Form("/list/next_action"), state: str = Form("")):
        """Undo a completion or a delete.

        Defaults to next_action rather than guessing the previous list — the
        edit page can move it anywhere afterwards. Reference/someday items that
        were trashed keep their nature better if the caller passes `state`.

        Books are the one case that must not fall through to that default: they
        are not in `user_lists()`, so undoing a finished book would file it as
        an action rather than returning it to its shelf.
        """
        if store.restore_book(item_id):
            return RedirectResponse(_safe_back(back, "/books"), status_code=303)

        target = state if state in {str(s) for s in ItemState.user_lists()} else str(
            ItemState.NEXT_ACTION
        )
        store.uncomplete(item_id, state=target)
        return RedirectResponse(_safe_back(back, "/list/next_action"), status_code=303)

    @app.get("/items/{item_id}/edit", response_class=HTMLResponse)
    def item_edit_form(request: Request, item_id: int, back: str = "/list/next_action"):
        item = store.get_item(item_id)
        if item is None:
            return RedirectResponse("/", status_code=303)
        dependencies = store.list_dependencies(item_id)
        return render(
            request,
            "edit.html",
            item=item,
            back=_safe_back(back, "/list/next_action"),
            contexts=store.list_contexts(),
            areas=store.list_areas(),
            projects=store.list_projects(),
            blocker_candidates=store.list_dependency_candidates(blocked_item_id=item_id),
            current_blocker_id=(
                dependencies[0]["prerequisite_item_id"] if dependencies else None
            ),
            time_estimates=TIME_ESTIMATES,
            state_choices=[(str(s), STATE_LABELS[s]) for s in ItemState],
        )

    @app.post("/items/{item_id}/edit")
    def item_edit(
        item_id: int,
        title: str = Form(...),
        notes: str = Form(""),
        state: str = Form(...),
        context_id: str = Form(""),
        energy: str = Form(""),
        time_estimate_min: str = Form(""),
        priority: str = Form(""),
        project_id: str = Form(""),
        area_id: str = Form(""),
        due_date: str = Form(""),
        defer_until: str = Form(""),
        waiting_on: str = Form(""),
        blocking_item_id: str = Form(""),
        back: str = Form("/list/next_action"),
    ):
        if state not in {str(s) for s in ItemState}:
            state = str(ItemState.NEXT_ACTION)

        store.update_item(
            item_id,
            title=title,
            notes=notes,
            state=state,
            context_id=_int_or_none(context_id),
            energy=_str_or_none(energy),
            time_estimate_min=_int_or_none(time_estimate_min),
            priority=_int_or_none(priority),
            project_id=_int_or_none(project_id),
            area_id=_int_or_none(area_id),
            due_date=_str_or_none(due_date),
            defer_until=_str_or_none(defer_until),
            waiting_on=_str_or_none(waiting_on),
        )
        blocker = _int_or_none(blocking_item_id)
        if state == ItemState.WAITING_FOR and blocker is not None:
            store.replace_dependencies(item_id, [blocker])
        else:
            store.replace_dependencies(item_id, [])
        return RedirectResponse(_safe_back(back, "/list/next_action"), status_code=303)

    # ── Projects ─────────────────────────────────────────────────────────────

    @app.get("/projects", response_class=HTMLResponse)
    def projects_page(request: Request):
        projects = store.list_projects()
        actions_by_project = {
            p["id"]: store.list_items(ItemState.NEXT_ACTION, project_id=p["id"])
            for p in projects
        }
        return render(
            request,
            "projects.html",
            projects=projects,
            actions_by_project=actions_by_project,
            contexts=store.list_contexts(),
            areas=store.list_areas(),
        )

    @app.post("/projects")
    def create_project(
        name: str = Form(...), outcome: str = Form(""), area_id: str = Form("")
    ):
        store.create_project(name, outcome=outcome, area_id=_int_or_none(area_id))
        return RedirectResponse("/projects", status_code=303)

    @app.post("/projects/{project_id}/actions")
    def add_project_action(
        project_id: int, title: str = Form(...), context_id: str = Form("")
    ):
        project = store.get_project(project_id)
        item_id = store.capture(title, source=Source.WEB)
        store.set_state(
            item_id,
            ItemState.NEXT_ACTION,
            project_id=project_id,
            context_id=_int_or_none(context_id),
            area_id=project["area_id"] if project else None,
        )
        return RedirectResponse("/projects", status_code=303)

    @app.post("/projects/{project_id}/complete")
    def complete_project(project_id: int):
        store.complete_project(project_id)
        return RedirectResponse("/projects", status_code=303)

    # ── Export ───────────────────────────────────────────────────────────────

    @app.post("/export")
    def export(request: Request):
        export_all(store, settings.export_dir)
        return RedirectResponse("/", status_code=303)

    return app


app = create_app()

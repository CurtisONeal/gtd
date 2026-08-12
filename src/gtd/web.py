"""FastAPI application.

Server-rendered forms with POST-redirect-GET. No JavaScript dependencies at
all: the clarify flow is a sequence of plain page loads, which means it works
with JS disabled, the back button behaves, and refreshing never re-submits.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .auth import SESSION_USER_KEY, LoginRateLimiter, verify_password
from .config import Settings, load_settings
from .db import Database
from .export import export_all
from .models import STATE_LABELS, ItemState, Source
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
            stalled_projects=[p for p in projects if p["open_actions"] == 0],
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

    @app.get("/list/{state}", response_class=HTMLResponse)
    def list_state(
        request: Request,
        state: str,
        deferred: int = 0,
        context_id: str = "",
        area_id: str = "",
    ):
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
            back=str(request.url.path),
        )

    @app.post("/items/{item_id}/complete")
    def item_complete(item_id: int, back: str = Form("/list/next_action")):
        store.complete(item_id)
        return RedirectResponse(_safe_back(back, "/list/next_action"), status_code=303)

    @app.post("/items/{item_id}/delete")
    def item_delete(item_id: int, back: str = Form("/list/next_action")):
        store.delete_item(item_id)
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

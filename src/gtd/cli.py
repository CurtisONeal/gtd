"""Command line entry point: `uv run gtd <command>`.

Deliberately tiny — argparse, no click dependency.
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from pathlib import Path

from .auth import MIN_PASSWORD_LENGTH, hash_password
from .config import PROJECT_ROOT, load_settings
from .db import Database
from .export import export_all
from .models import ItemState, Source
from .store import Store


def _store() -> tuple[Store, object]:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init_schema()
    return Store(db), settings


def cmd_init_db(_args: argparse.Namespace) -> int:
    store, settings = _store()
    print(f"Database ready at {settings.db_path}")
    print(f"  contexts: {len(store.list_contexts())}")
    print(f"  areas:    {len(store.list_areas())}")
    if store.user_count() == 0:
        print("\nNo user yet — run `uv run gtd set-password` before starting the server.")
    return 0


def cmd_set_password(args: argparse.Namespace) -> int:
    """Create or change the login. The password is never echoed, never logged,
    and only its argon2id hash is stored."""
    store, _ = _store()
    username = (args.username or "").strip().lower()
    if not username:
        username = input("Username [curtis]: ").strip().lower() or "curtis"

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    existed = store.get_user(username) is not None
    store.upsert_user(username, password_hash)
    print(f"{'Updated' if existed else 'Created'} login for '{username}'.")
    return 0


def cmd_export(_args: argparse.Namespace) -> int:
    store, settings = _store()
    written = export_all(store, settings.export_dir)
    print(f"Exported {len(written)} files to {settings.export_dir}")
    for path in written:
        print(f"  {path.name}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    store, _ = _store()
    text = " ".join(args.text).strip()
    if not text:
        print("Nothing to capture.", file=sys.stderr)
        return 1
    item_id = store.capture(text, source=Source.CLI)
    print(f"Captured #{item_id}: {text}")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    store, settings = _store()
    counts = store.counts_by_state()
    print(f"Database: {settings.db_path}\n")
    for state in ItemState.user_lists():
        print(f"  {state:<14} {counts.get(str(state), 0):>4}")
    print(f"  {'done':<14} {counts.get(str(ItemState.DONE), 0):>4}")
    projects = store.list_projects()
    stalled = [p for p in projects if p["open_actions"] == 0]
    print(f"\n  projects       {len(projects):>4}", end="")
    print(f"  ({len(stalled)} stalled)" if stalled else "")
    return 0


def cmd_gen_secret(_args: argparse.Namespace) -> int:
    """Print a session secret suitable for GTD_SESSION_SECRET."""
    print(secrets.token_urlsafe(48))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the web server, honouring GTD_LOCAL_ONLY.

    Preferred over invoking uvicorn directly: with GTD_LOCAL_ONLY=true this
    refuses to bind anything but loopback, rather than quietly doing what it was
    told. (The app also rejects non-loopback *callers* at runtime, so the
    guarantee survives someone bypassing this command — see ADR-010.)
    """
    import uvicorn

    settings = load_settings()
    store, _ = _store()

    host = args.host or settings.effective_host
    port = args.port or settings.port

    if settings.local_only and host not in ("127.0.0.1", "::1", "localhost"):
        print(
            f"Refusing to bind {host}: GTD_LOCAL_ONLY=true means this instance "
            "serves only this machine.\n"
            "Unset GTD_LOCAL_ONLY in .env if this is deliberate — but do not do "
            "that on a work machine (see ADR-008).",
            file=sys.stderr,
        )
        return 2

    if store.user_count() == 0:
        print("No login exists yet. Run `gtd set-password` first.", file=sys.stderr)
        return 1

    scope = "this machine only" if settings.local_only else "all matching interfaces"
    print(f"Serving on http://{host}:{port}  ({scope})")
    uvicorn.run("gtd.web:app", host=host, port=port, reload=args.reload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gtd", description="Self-hosted GTD system")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create the database and seed defaults").set_defaults(
        func=cmd_init_db
    )

    sp = sub.add_parser("set-password", help="Create or change the web login")
    sp.add_argument("--username", help="Defaults to 'curtis' if omitted")
    sp.set_defaults(func=cmd_set_password)

    sub.add_parser("export", help="Write markdown exports of every list").set_defaults(
        func=cmd_export
    )

    cp = sub.add_parser("capture", help="Capture an item straight into the inbox")
    cp.add_argument("text", nargs="+")
    cp.set_defaults(func=cmd_capture)

    sv = sub.add_parser("serve", help="Run the web server (respects GTD_LOCAL_ONLY)")
    sv.add_argument("--host", help="Override the configured host")
    sv.add_argument("--port", type=int, help="Override the configured port")
    sv.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    sv.set_defaults(func=cmd_serve)

    sub.add_parser("status", help="Show counts per list").set_defaults(func=cmd_status)
    sub.add_parser("gen-secret", help="Print a session secret for .env").set_defaults(
        func=cmd_gen_secret
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

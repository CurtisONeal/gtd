"""Environment-driven configuration.

Everything that differs between "running on localhost tonight" and "running
behind TLS on a real host later" lives here, so phased deployment never needs a
code change — only a different .env.
"""

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader.

    Deliberately not python-dotenv — this is a dozen lines and saves a
    dependency. Real environment variables always win over .env values.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve(path_str: str) -> Path:
    """Relative paths resolve from the project root, not the current cwd, so the
    app finds the same database whether launched from the repo or a service."""
    path = Path(path_str).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path)


@dataclass(frozen=True)
class Settings:
    db_path: Path
    export_dir: Path
    session_secret: str
    secure_cookies: bool
    session_max_age: int
    capture_token: str | None
    local_only: bool
    host: str
    port: int
    # Defaulted so a Settings can still be built field-by-field (tests do) without
    # every caller having to care about backups. `load_settings` always supplies
    # them from the environment.
    backup_dir: Path = Path("backups")
    backup_remote: str | None = None
    backup_keep: int = 14
    backup_identity: Path | None = None
    backup_cloud: str | None = None
    backup_age_recipient: str | None = None
    backup_age_identity: Path | None = None

    @property
    def capture_api_enabled(self) -> bool:
        return bool(self.capture_token)

    @property
    def effective_host(self) -> str:
        """`local_only` wins over any configured host.

        A work instance must not be reachable from another machine, and a
        setting that only takes effect if you remember to pass the right
        `--host` is not a constraint — it's a suggestion. See ADR-008/ADR-010.
        """
        return "127.0.0.1" if self.local_only else self.host


def load_settings(env_file: Path | None = None) -> Settings:
    _load_dotenv(env_file or (PROJECT_ROOT / ".env"))

    secret = os.environ.get("GTD_SESSION_SECRET", "").strip()
    if not secret:
        # Ephemeral fallback so tests and first-run don't explode. Sessions do
        # not survive a restart with this, which is the intended nudge to set a
        # real one — see .env.example.
        secret = secrets.token_urlsafe(48)

    return Settings(
        db_path=_resolve(os.environ.get("GTD_DB_PATH", "gtd.db")),
        export_dir=_resolve(os.environ.get("GTD_EXPORT_DIR", "exports")),
        session_secret=secret,
        secure_cookies=_as_bool(os.environ.get("GTD_SECURE_COOKIES"), False),
        session_max_age=int(os.environ.get("GTD_SESSION_MAX_AGE", 60 * 60 * 24 * 30)),
        capture_token=os.environ.get("GTD_CAPTURE_TOKEN", "").strip() or None,
        local_only=_as_bool(os.environ.get("GTD_LOCAL_ONLY"), False),
        host=os.environ.get("GTD_HOST", "127.0.0.1").strip() or "127.0.0.1",
        port=int(os.environ.get("GTD_PORT", 8765)),
        backup_dir=_resolve(os.environ.get("GTD_BACKUP_DIR", "backups")),
        # user@host:/path — where snapshots are copied after being verified.
        backup_remote=os.environ.get("GTD_BACKUP_REMOTE", "").strip() or None,
        backup_keep=int(os.environ.get("GTD_BACKUP_KEEP", 14)),
        backup_identity=(
            Path(os.environ["GTD_BACKUP_IDENTITY"]).expanduser()
            if os.environ.get("GTD_BACKUP_IDENTITY", "").strip()
            else None
        ),
        # rclone remote, e.g. gdrive:gtd-backups. Anything sent here is
        # encrypted first — it is the only destination a third party holds.
        backup_cloud=os.environ.get("GTD_BACKUP_CLOUD", "").strip() or None,
        # age *public* key. Encrypting needs only this, so the machine taking
        # backups cannot read its own cloud archive.
        backup_age_recipient=os.environ.get("GTD_BACKUP_AGE_RECIPIENT", "").strip() or None,
        backup_age_identity=(
            Path(os.environ["GTD_BACKUP_AGE_IDENTITY"]).expanduser()
            if os.environ.get("GTD_BACKUP_AGE_IDENTITY", "").strip()
            else None
        ),
    )

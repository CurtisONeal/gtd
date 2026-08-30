import os
import tempfile

# Importing `gtd.web` runs `app = create_app()` at module level, which calls
# `init_schema()` against whatever GTD_DB_PATH resolves to — and that defaults
# to `gtd.db` relative to the working directory. Running the suite from the repo
# root therefore opened the *live* database, and now that init_schema applies
# migrations rather than only CREATE TABLE IF NOT EXISTS, that means running
# tests would alter real data. Redirect the default before any test module is
# imported. Every fixture below still uses its own tmp_path file.
os.environ.setdefault("GTD_DB_PATH", os.path.join(tempfile.mkdtemp(), "import-time.db"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from gtd.auth import hash_password  # noqa: E402
from gtd.config import Settings  # noqa: E402
from gtd.db import Database  # noqa: E402
from gtd.store import Store  # noqa: E402
from gtd.web import create_app  # noqa: E402

PASSWORD = "a-sufficiently-long-password"
USERNAME = "curtis"


@pytest.fixture
def db(tmp_path):
    """A real SQLite file per test, in a temp dir — no shared state, no mocks."""
    database = Database(tmp_path / "test.db")
    database.init_schema()
    return database


@pytest.fixture
def store(db):
    return Store(db)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        db_path=tmp_path / "web.db",
        export_dir=tmp_path / "exports",
        session_secret="test-secret-not-used-anywhere-real",
        secure_cookies=False,
        session_max_age=3600,
        capture_token="test-capture-token",
        local_only=False,
        host="127.0.0.1",
        port=8765,
    )


@pytest.fixture
def app(settings):
    application = create_app(settings)
    application.state.store.upsert_user(USERNAME, hash_password(PASSWORD))
    return application


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def signed_in(client):
    """A client that has already logged in — most route tests need one."""
    client.post("/login", data={"username": USERNAME, "password": PASSWORD})
    return client

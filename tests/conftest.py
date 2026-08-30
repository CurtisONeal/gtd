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

from gtd.db import Database  # noqa: E402
from gtd.store import Store  # noqa: E402


@pytest.fixture
def db(tmp_path):
    """A real SQLite file per test, in a temp dir — no shared state, no mocks."""
    database = Database(tmp_path / "test.db")
    database.init_schema()
    return database


@pytest.fixture
def store(db):
    return Store(db)

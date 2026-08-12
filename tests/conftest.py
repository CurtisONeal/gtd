import pytest

from gtd.db import Database
from gtd.store import Store


@pytest.fixture
def db(tmp_path):
    """A real SQLite file per test, in a temp dir — no shared state, no mocks."""
    database = Database(tmp_path / "test.db")
    database.init_schema()
    return database


@pytest.fixture
def store(db):
    return Store(db)

"""Shared fixtures: every test runs against a throwaway copy of homebase_original.db,
never the real working DB."""

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import copy_db


@pytest.fixture
def test_db(tmp_path, monkeypatch):
    path = tmp_path / "test.db"
    copy_db(config.ORIGINAL_DB, path)
    monkeypatch.setattr(config, "WORKING_DB", path)
    return path


@pytest.fixture
def client(test_db, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    from app.main import app
    with TestClient(app) as c:
        yield c

"""Shared fixtures: every test runs against its own throwaway Postgres database, never a real one.

The Postgres server, in order of preference:
  1. TEST_DATABASE_ADMIN_URL (environment or .env): an existing server where the tests may create and drop databases,
     e.g. postgresql://postgres@localhost:5432/postgres
  2. The portable PostgreSQL in backend/.pg/pgsql (download it once with: python scripts/get_test_postgres.py). The
     tests start it in a temp folder on a free port for the run, and stop it at the end. Nothing is installed.
A template database is built once per run exactly the way the app builds a real one (Alembic migrations, then the
content from content/: app.db.ensure_database). Each test then gets a fresh copy of it (CREATE DATABASE ... TEMPLATE),
pointed to by config.DATABASE_URL_OVERRIDE, and dropped afterwards.
"""

import itertools
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import close_pools, ensure_database

PG_DIR = config.BACKEND_DIR / ".pg" / "pgsql" / "bin"
TEMPLATE = "beefit_test_template"
_counter = itertools.count()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _url(admin: str, dbname: str) -> str:
    return psycopg.conninfo.make_conninfo(admin, dbname=dbname)


def _admin_exec(admin: str, sql: str) -> None:
    with psycopg.connect(admin, autocommit=True) as c:
        c.execute(sql)


def _stop_leftovers(bin_dir: Path) -> None:
    """A test run that was killed (not just failed) can't stop its server: stop and remove any left in the temp folder.
    Only ones over an hour old (a full run takes minutes), so a run going on in another terminal is left alone."""
    for old in Path(tempfile.gettempdir()).glob("beefit_pg_*"):
        if time.time() - old.stat().st_mtime < 3600:
            continue
        if (old / "data" / "postmaster.pid").exists():
            subprocess.run([str(bin_dir / "pg_ctl"), "-D", str(old / "data"), "-m", "immediate", "-w", "stop"],
                           capture_output=True)
        shutil.rmtree(old, ignore_errors=True)


@pytest.fixture(scope="session")
def pg_admin_url():
    admin = config.get_secret("TEST_DATABASE_ADMIN_URL")
    if admin:
        yield admin
        return
    bin_dir = Path(os.environ.get("BEE_PG_BIN") or PG_DIR)
    if not (bin_dir / ("initdb.exe" if os.name == "nt" else "initdb")).exists():
        pytest.exit("No Postgres for the tests. Run `python scripts/get_test_postgres.py` once (portable, no install), "
                    "or set TEST_DATABASE_ADMIN_URL to a server the tests may create databases on.", returncode=2)
    _stop_leftovers(bin_dir)
    data = Path(tempfile.mkdtemp(prefix="beefit_pg_"))   # not under OneDrive: sync can lock database files
    port = _free_port()
    run = lambda *a: subprocess.run([str(bin_dir / a[0]), *a[1:]], check=True, capture_output=True)  # noqa: E731
    run("initdb", "-D", str(data / "data"), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale")
    # The server inherits pg_ctl's stdout / stderr, so they must not be pipes (reading them would wait for the server
    # to exit); its output goes to log.txt.
    subprocess.run([str(bin_dir / "pg_ctl"), "-D", str(data / "data"), "-o", f"-p {port} -c listen_addresses=localhost "
                    "-c fsync=off -c synchronous_commit=off -c full_page_writes=off", "-l", str(data / "log.txt"),
                    "-w", "start"], check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    try:
        yield f"postgresql://postgres@localhost:{port}/postgres"
    finally:
        close_pools()
        subprocess.run([str(bin_dir / "pg_ctl"), "-D", str(data / "data"), "-m", "immediate", "-w", "stop"],
                       capture_output=True)
        shutil.rmtree(data, ignore_errors=True)


@pytest.fixture(scope="session")
def template_db(pg_admin_url):
    """The seeded template every test's database is copied from (built the way the app builds a real database)."""
    _admin_exec(pg_admin_url, f'DROP DATABASE IF EXISTS "{TEMPLATE}" WITH (FORCE)')
    _admin_exec(pg_admin_url, f'CREATE DATABASE "{TEMPLATE}"')
    url = _url(pg_admin_url, TEMPLATE)
    old = config.DATABASE_URL_OVERRIDE
    config.DATABASE_URL_OVERRIDE = url
    try:
        ensure_database()
    finally:
        close_pools(url)
        config.DATABASE_URL_OVERRIDE = old
    yield url
    _admin_exec(pg_admin_url, f'DROP DATABASE IF EXISTS "{TEMPLATE}" WITH (FORCE)')


@pytest.fixture
def fresh_db(pg_admin_url, template_db, monkeypatch):
    """A brand-new database for one test, copied from the template. Yields its URL."""
    name = f"beefit_test_{os.getpid()}_{next(_counter)}"
    _admin_exec(pg_admin_url, f'CREATE DATABASE "{name}" TEMPLATE "{TEMPLATE}"')
    url = _url(pg_admin_url, name)
    monkeypatch.setattr(config, "DATABASE_URL_OVERRIDE", url)
    try:
        yield url
    finally:
        close_pools(url)
        _admin_exec(pg_admin_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def test_db(fresh_db):
    return fresh_db


@pytest.fixture
def empty_db(pg_admin_url, monkeypatch):
    """A database with nothing in it at all (no tables, no content), like a brand-new Neon project. Yields its URL."""
    name = f"beefit_empty_{os.getpid()}_{next(_counter)}"
    _admin_exec(pg_admin_url, f'CREATE DATABASE "{name}"')
    url = _url(pg_admin_url, name)
    monkeypatch.setattr(config, "DATABASE_URL_OVERRIDE", url)
    try:
        yield url
    finally:
        close_pools(url)
        _admin_exec(pg_admin_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def client(test_db, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    from app.main import app
    from app.security import limiter
    limiter.reset()                       # every test starts with fresh rate-limit counters
    with TestClient(app) as c:
        yield c

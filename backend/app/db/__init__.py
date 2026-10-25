"""Postgres access for Bee Fit (DATABASE_URL; a free Neon database in production, since 2026-10-25).

It replaced a SQLite file on a Render persistent disk, so the app keeps nothing on local disk. The schema comes from
Alembic migrations (backend/migrations); the content tables (exercises, quiz questions, protocols, sources) are seeded
from content/ by app/db/seed.py. Startup runs both (ensure_database below).

connect() / connect_readonly() hand out pooled psycopg 3 connections wrapped to behave the way the code was written
for SQLite, so queries didn't all have to be rewritten at once:
  * `?` and `:name` placeholders work (translated to psycopg's %s / %(name)s), and a literal % is escaped.
  * Rows are read by column name or position, and dict(row) works (like sqlite3.Row).
  * `with conn:` commits (or rolls back on an error) WITHOUT closing; close() returns the connection to the pool.
  * After an INSERT, result.lastrowid is the new row's id (RETURNING id is added for tables that have one).
  * Booleans are stored as 0/1 and dates/datetimes as ISO text, exactly as the SQLite adapter stored them.
connect_readonly() connections run every transaction READ ONLY, so Postgres itself refuses a write through them (the
MCP tools use these, so "read-only" holds even if a query were ever written wrongly).
"""

import hashlib
import logging
import re
import threading
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Iterable, Sequence

import psycopg
from psycopg import errors  # noqa: F401  (re-exported for callers that catch specific errors)
from psycopg.pq import TransactionStatus
from psycopg_pool import ConnectionPool

from app import config

log = logging.getLogger(__name__)

IntegrityError = psycopg.IntegrityError     # what a CHECK / NOT NULL / UNIQUE / FK violation raises
DatabaseError = psycopg.Error

# INSERTs into these get "RETURNING id" added so lastrowid works (every table with an id column).
_NO_ID_TABLES = {"app_meta", "alembic_version"}


# ---------------------------------------------------------------- rows

class Row:
    """A result row: row["col"], row[0], dict(row), iteration over values (the sqlite3.Row interface)."""
    __slots__ = ("_names", "_values", "_index")

    def __init__(self, names: tuple[str, ...], index: dict[str, int], values: Sequence[Any]):
        self._names, self._index, self._values = names, index, tuple(values)

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._values[self._index[key]]

    def keys(self) -> list[str]:
        return list(self._names)

    def get(self, key, default=None):
        i = self._index.get(key)
        return default if i is None else self._values[i]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._names, self._values))!r})"


def _row_factory(cursor):
    names = tuple(c.name for c in cursor.description or ())
    index = {n: i for i, n in enumerate(names)}
    return lambda values: Row(names, index, values)


# ---------------------------------------------------------------- SQL and parameters

@lru_cache(maxsize=2048)
def to_pg(sql: str) -> str:
    """`?` -> %s, `:name` -> %(name)s, `%` -> %%, outside quoted strings, quoted identifiers and comments."""
    out, i, n = [], 0, len(sql)
    while i < n:
        c = sql[i]
        if c in "'\"":                                     # a quoted string or identifier: copy it whole
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:      # '' or "" escape
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i:j + 1].replace("%", "%%"))
            i = j + 1
        elif c == "-" and sql.startswith("--", i):         # a comment: to the end of the line
            j = sql.find("\n", i)
            j = n if j == -1 else j
            out.append(sql[i:j].replace("%", "%%"))
            i = j
        elif c == "?":
            out.append("%s")
            i += 1
        elif c == ":" and i + 1 < n and (sql[i + 1].isalpha() or sql[i + 1] == "_") and (i == 0 or sql[i - 1] != ":"):
            m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", sql[i + 1:])
            out.append(f"%({m.group(0)})s")
            i += 1 + len(m.group(0))
        elif c == "%":
            out.append("%%")
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _value(v):
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, datetime):
        return v.isoformat(" ")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _params(params):
    if params is None:
        return None
    if isinstance(params, dict):
        return {k: _value(v) for k, v in params.items()}
    return [_value(v) for v in params]


_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+\"?(\w+)", re.I)


# ---------------------------------------------------------------- connections

class Result:
    """What execute() returns: fetchone / fetchall / iteration / rowcount / lastrowid."""

    def __init__(self, cursor, lastrowid=None):
        self._cur, self.lastrowid = cursor, lastrowid

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def fetchone(self):
        return self._cur.fetchone() if self._cur.description else None

    def fetchall(self) -> list:
        return self._cur.fetchall() if self._cur.description else []

    def __iter__(self):
        return iter(self.fetchall())


class Connection:
    """A pooled psycopg connection with the SQLite-shaped interface the app uses (see the module docstring)."""

    def __init__(self, pg: psycopg.Connection, pool: ConnectionPool | None):
        self._pg, self._pool = pg, pool

    @property
    def raw(self) -> psycopg.Connection:
        return self._pg

    def execute(self, sql: str, params=None) -> Result:
        q = to_pg(sql) if params is not None else sql   # no params: psycopg sends the text as is (no % handling)
        m = _INSERT.match(q)
        returning = bool(m) and m.group(1).lower() not in _NO_ID_TABLES and not re.search(r"\bRETURNING\b", q, re.I)
        if returning:
            q = q.rstrip().rstrip(";") + " RETURNING id"
        cur = self._pg.cursor(row_factory=_row_factory)
        cur.execute(q, _params(params))
        lastrowid = None
        if returning:
            row = cur.fetchone()
            lastrowid = row[0] if row else None
        return Result(cur, lastrowid)

    def executemany(self, sql: str, seq: Iterable) -> None:
        cur = self._pg.cursor()
        cur.executemany(to_pg(sql), [_params(p) for p in seq])

    def commit(self) -> None:
        self._pg.commit()

    def rollback(self) -> None:
        self._pg.rollback()

    def pipeline(self):
        """Batch many statements without waiting for each reply (fast over the network)."""
        return self._pg.pipeline()

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._pg.commit()
        else:
            self._pg.rollback()
        return False

    def close(self) -> None:
        if self._pg is None:
            return
        pg, self._pg = self._pg, None
        try:
            if pg.info.transaction_status != TransactionStatus.IDLE and not pg.closed:
                pg.rollback()          # an unfinished read: nothing to keep
        finally:
            if self._pool is not None:
                self._pool.putconn(pg)
            else:
                pg.close()


_pools: dict[tuple[str, bool], ConnectionPool] = {}
_pools_lock = threading.Lock()


def _configure_readonly(pg: psycopg.Connection) -> None:
    pg.read_only = True


def _pool(read_only: bool) -> ConnectionPool:
    url = config.database_url()
    key = (url, read_only)
    with _pools_lock:
        pool = _pools.get(key)
        if pool is None:
            pool = ConnectionPool(
                url, min_size=0, max_size=10, open=True, name=f"bee-fit{'-ro' if read_only else ''}",
                # prepare_threshold=None: no server-side prepared statements, so a pgbouncer-style pooler (Neon's
                # "-pooler" address) is safe. check: a connection idled out by a sleeping Neon compute is replaced.
                kwargs={"prepare_threshold": None, "autocommit": False},
                configure=_configure_readonly if read_only else None,
                check=ConnectionPool.check_connection,
            )
            _pools[key] = pool
        return pool


def connect() -> Connection:
    pool = _pool(False)
    return Connection(pool.getconn(), pool)


def connect_readonly() -> Connection:
    """A connection whose every transaction is READ ONLY: Postgres refuses any write through it."""
    pool = _pool(True)
    return Connection(pool.getconn(), pool)


def connect_direct(url: str | None = None, autocommit: bool = False) -> Connection:
    """An unpooled connection (scripts, migrations, test setup)."""
    return Connection(psycopg.connect(url or config.database_url(), autocommit=autocommit, prepare_threshold=None),
                      None)


def close_pools(url: str | None = None) -> None:
    """Close the pools (all of them, or those for one database URL), e.g. before dropping a test database."""
    with _pools_lock:
        for key in [k for k in _pools if url is None or k[0] == url]:
            _pools.pop(key).close()


# ---------------------------------------------------------------- startup: schema + content

META_KEY = "content_sha256"


def ensure_database() -> str:
    """Run at startup. Brings the schema up to date (Alembic upgrade head), then makes sure the content tables match
    this deploy's content/ files. Returns what it did with the content:
      "seeded"     an empty database: content loaded for the first time
      "unchanged"  the content already matches: nothing touched
      "refreshed"  this deploy ships new content: content tables replaced, every account and all user data kept
    """
    from app.db.migrate import upgrade_to_head   # local imports: both import this module
    from app.db.seed import content_fingerprint, seed_content
    upgrade_to_head()
    want = content_fingerprint()
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (META_KEY,)).fetchone()
        have = row[0] if row else None
        first = conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 0
    finally:
        conn.close()
    if have == want and not first:
        return "unchanged"
    seed_content()
    log.warning("Content %s: %s.", "loaded into an empty database" if first else "changed, content tables refreshed",
                want[:12])
    return "seeded" if first else "refreshed"


def table_counts(conn: Connection) -> dict[str, int]:
    tables = [r[0] for r in conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
        "AND table_type = 'BASE TABLE' AND table_name <> 'alembic_version' ORDER BY table_name")]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

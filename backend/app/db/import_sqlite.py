"""One-time move of the live accounts from the old SQLite database (homebase.db on the Render disk) into Postgres.

Run from backend/, with DATABASE_URL pointing at the new Postgres database:
    .venv\\Scripts\\python.exe -m app.db.import_sqlite path\\to\\homebase.db

What it does:
  1. Brings the Postgres schema up to date and loads the content (the same as startup), so every exercise a log or
     favorite points at exists.
  2. Copies every user table (accounts, quiz answers, calendar days, workout and cardio logs, measurements, favorites,
     built workouts, safety events) and the agent_runs token log, keeping the ids, so sign-in tokens issued by the old
     service keep working if APP_SECRET_KEY is the same. Rows saved under an older schema are brought up to date first
     (app/db/reset.py: RENAMED_COLUMNS, migrate_quiz_profile). A row Postgres rejects (it breaks a CHECK, or points at
     something that no longer exists) is skipped and counted, never imported half-broken.
  3. Moves the id counters past the imported ids, so new rows don't collide.

It refuses to run if Postgres already has accounts (it's for an empty database; nothing is overwritten). Password
hashes come across as they are: old scrypt hashes still sign in, and are upgraded to Argon2 the first time each person
signs in (app/security.py). The SQLite file itself is only read.
"""

import sqlite3
import sys
from pathlib import Path

from app.db import DatabaseError, connect, ensure_database
from app.db.reset import RENAMED_COLUMNS, ROW_MIGRATIONS, USER_TABLES

TABLES = (*USER_TABLES, "agent_runs")


def _old_rows(path: Path, table: str) -> list[dict]:
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
    except sqlite3.OperationalError:   # an older database without this table
        return []
    finally:
        conn.close()


def _columns(conn, table: str) -> list[str]:
    """Columns we may write (not generated ones like quiz_profiles.needs_clinical_review). Never users.email: in
    Postgres that column means "an email Google / Microsoft verified" (app/oauth.py links sign-ins by it), and the
    SQLite email column (accounts from before usernames) was never verified. Those emails become the username."""
    return [r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = ? AND is_generated = 'NEVER' ORDER BY ordinal_position", (table,))
        if not (table == "users" and r[0] == "email")]


def import_sqlite(path: Path) -> dict:
    """Returns {"imported": {table: n}, "skipped": {table: n}}."""
    if not path.exists():
        raise SystemExit(f"Not found: {path}")
    ensure_database()
    conn = connect()
    try:
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise SystemExit("Postgres already has accounts; this import is only for an empty database.")
        summary = {"imported": {}, "skipped": {}}
        with conn:
            for table in TABLES:
                rows = _old_rows(path, table)
                if table in ROW_MIGRATIONS:
                    rows = [ROW_MIGRATIONS[table](r) for r in rows]
                cols = _columns(conn, table)
                renamed = {new: old for new, old in RENAMED_COLUMNS.get(table, {}).items()}
                ok = skipped = 0
                for r in rows:
                    values = {c: r[c] if c in r else r.get(renamed.get(c, c)) for c in cols
                              if c in r or renamed.get(c) in r}
                    names = list(values)
                    sql = (f"INSERT INTO {table} ({', '.join(names)}) "
                           f"VALUES ({', '.join('?' for _ in names)})")
                    conn.execute("SAVEPOINT row")
                    try:
                        conn.execute(sql, [values[c] for c in names])
                        conn.execute("RELEASE SAVEPOINT row")
                        ok += 1
                    except DatabaseError:   # a CHECK / foreign key / type Postgres refuses: skip the row
                        conn.execute("ROLLBACK TO SAVEPOINT row")
                        skipped += 1
                summary["imported"][table], summary["skipped"][table] = ok, skipped
                if "id" in cols:   # move the identity counter past the imported ids
                    conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                                 f"GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), 1), "
                                 f"(SELECT COUNT(*) > 0 FROM {table}))")
    finally:
        conn.close()
    return summary


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.db.import_sqlite path/to/homebase.db")
    result = import_sqlite(Path(sys.argv[1]))
    for table in TABLES:
        print(f"  {table:20} imported {result['imported'][table]:5}   skipped {result['skipped'][table]}")

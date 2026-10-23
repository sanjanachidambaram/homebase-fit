"""Rebuild the working database (homebase.db) from the clean original (homebase_original.db).

Run from backend/:
    .venv\\Scripts\\python.exe -m app.db.reset                 wipe all user data (a clean demo database)
    .venv\\Scripts\\python.exe -m app.db.reset --keep-users    refresh the content but keep every account

Two ways to use it:
  * reset()          Wipes everything users created (accounts, quiz answers, logs, measurements, calendar,
                     safety events, favorites) and restores the seeded content. Only on purpose.
  * refresh_content() Restores the seeded content and schema, then carries every account and all their data
                     back in, so the same sign-ins keep working. app.db.seed uses this by default.
                     (Incident 2026-10-22: seed used to wipe accounts; a content rebuild during a live session
                     deleted a signed-in user, who was then signed out and couldn't sign back in.)

Always kept: the agent_runs token log. It's the measurement record for the tokenomics report. After a full
reset its user_id is cleared, since the accounts are gone.

Carrying data across a schema change: only columns that exist in both versions are copied (generated columns
are recomputed), and rows the new schema rejects (e.g. a favorite for an exercise that was removed from
content) are dropped and counted, never silently kept broken.
"""

import sqlite3
import sys

from app import config
from app.db import connect, copy_db, table_counts

# Parents first, so ids line up. (app/users.py USER_DATA_TABLES lists the same tables for account deletion.)
USER_TABLES = ("users", "quiz_profiles", "exercise_favorites", "measurements", "calendar_entries", "cardio_logs",
               "built_workouts", "workout_logs", "safety_events")


def _read(table: str) -> list[dict]:
    if not config.WORKING_DB.exists():
        return []
    conn = sqlite3.connect(config.WORKING_DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
    except sqlite3.OperationalError:   # older database without this table
        return []
    finally:
        conn.close()


def _insertable(conn: sqlite3.Connection, table: str) -> list[str]:
    """Columns we may write: not generated (table_xinfo hidden = 2 or 3)."""
    return [r[1] for r in conn.execute(f"PRAGMA table_xinfo({table})") if r[6] == 0]


def _restore(keep_users: bool) -> dict:
    if not config.ORIGINAL_DB.exists():
        raise SystemExit(f"{config.ORIGINAL_DB.name} not found. Build it first with: python -m app.db.seed")
    saved = {t: _read(t) for t in (*USER_TABLES, "agent_runs")} if keep_users else {"agent_runs": _read("agent_runs")}
    copy_db(config.ORIGINAL_DB, config.WORKING_DB)

    summary = {"kept": {}, "dropped": {}}
    conn = connect()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")   # insert in any order; checked below
        with conn:
            for table, rows in saved.items():
                if not rows:
                    continue
                cols = [c for c in _insertable(conn, table) if c in rows[0]]
                sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
                kept = dropped = 0
                for r in rows:
                    values = [None if (c == "user_id" and table == "agent_runs" and not keep_users) else r[c]
                              for c in cols]
                    try:
                        conn.execute(sql, values)
                        kept += 1
                    except sqlite3.IntegrityError:   # a CHECK / NOT NULL / UNIQUE the new schema rejects
                        dropped += 1
                summary["kept"][table], summary["dropped"][table] = kept, dropped
            # Rows pointing at something that no longer exists: unlink token-log rows, drop the rest.
            for table, rowid, parent, _ in conn.execute("PRAGMA foreign_key_check").fetchall():
                if table == "agent_runs":
                    conn.execute("UPDATE agent_runs SET user_id = NULL WHERE rowid = ?", (rowid,))
                else:
                    conn.execute(f"DELETE FROM {table} WHERE rowid = ?", (rowid,))
                    summary["kept"][table] -= 1
                    summary["dropped"][table] = summary["dropped"].get(table, 0) + 1
        conn.execute("PRAGMA foreign_keys = ON")
    finally:
        conn.close()
    return summary


def reset() -> int:
    """Wipe all user data; returns how many agent_runs rows were carried over."""
    return _restore(keep_users=False)["kept"].get("agent_runs", 0)


def refresh_content() -> dict:
    """New content and schema, same accounts: {"kept": {table: n}, "dropped": {table: n}}."""
    return _restore(keep_users=True)


if __name__ == "__main__":
    if "--keep-users" in sys.argv:
        result = refresh_content()
        print(f"Refreshed {config.WORKING_DB.name} from {config.ORIGINAL_DB.name}, keeping every account.")
        print(f"  kept: {result['kept']}")
        if any(result["dropped"].values()):
            print(f"  dropped (no longer valid): {result['dropped']}")
    else:
        kept = reset()
        print(f"Reset {config.WORKING_DB.name} from {config.ORIGINAL_DB.name} (kept {kept} agent_runs rows).")
    conn = connect()
    counts = table_counts(conn)
    conn.close()
    for table, n in counts.items():
        print(f"  {table:28} {n}")

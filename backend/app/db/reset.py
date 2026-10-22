"""Reset the working database to the clean original.

Run from backend/:
    .venv\\Scripts\\python.exe -m app.db.reset

Wipes everything users created (accounts, logs, measurements, safety events, favorites)
and restores the seeded content.

Kept: the agent_runs token log. It's the measurement record for the tokenomics report, so a
reset carries those rows over (with user_id cleared, since the accounts are gone).
"""

import sqlite3

from app import config
from app.db import connect, copy_db, table_counts


def _saved_agent_runs() -> list[dict]:
    if not config.WORKING_DB.exists():
        return []
    conn = sqlite3.connect(config.WORKING_DB)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM agent_runs ORDER BY id")]
    except sqlite3.OperationalError:   # older database without the table
        return []
    finally:
        conn.close()


def reset() -> int:
    """Restore the working DB from the original; returns how many agent_runs rows were carried over."""
    if not config.ORIGINAL_DB.exists():
        raise SystemExit(f"{config.ORIGINAL_DB.name} not found. Build it first with: python -m app.db.seed")
    runs = _saved_agent_runs()
    copy_db(config.ORIGINAL_DB, config.WORKING_DB)
    if runs:
        conn = connect()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(agent_runs)")]
        keep = [c for c in cols if c in runs[0]]   # tolerate schema changes between versions
        with conn:
            conn.executemany(
                f"INSERT INTO agent_runs ({', '.join(keep)}) VALUES ({', '.join('?' for _ in keep)})",
                [[None if c == "user_id" else r[c] for c in keep] for r in runs])
        conn.close()
    return len(runs)


if __name__ == "__main__":
    kept = reset()
    conn = connect()
    counts = table_counts(conn)
    conn.close()
    print(f"Reset {config.WORKING_DB.name} from {config.ORIGINAL_DB.name} (kept {kept} agent_runs rows).")
    for table, n in counts.items():
        print(f"  {table:28} {n}")

"""Reset the working database to the clean original.

Run from backend/:
    .venv\\Scripts\\python.exe -m app.db.reset

Wipes everything users created (accounts, logs, measurements, safety events)
and restores the seeded content.
"""

from app.config import ORIGINAL_DB, WORKING_DB
from app.db import connect, copy_db, table_counts


def reset() -> None:
    if not ORIGINAL_DB.exists():
        raise SystemExit(f"{ORIGINAL_DB.name} not found. Build it first with: python -m app.db.seed")
    copy_db(ORIGINAL_DB, WORKING_DB)


if __name__ == "__main__":
    reset()
    conn = connect()
    counts = table_counts(conn)
    conn.close()
    print(f"Reset {WORKING_DB.name} from {ORIGINAL_DB.name}.")
    for table, n in counts.items():
        print(f"  {table:28} {n}")

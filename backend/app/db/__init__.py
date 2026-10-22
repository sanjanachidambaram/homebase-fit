"""SQLite access for HomeBase Fit.

Two files, same pattern as the shop project:
  homebase_original.db  clean schema + seeded content (built by seed.py)
  homebase.db           working copy the app reads and writes (reset.py restores it)
"""

import sqlite3
from pathlib import Path

from app.config import ORIGINAL_DB, WORKING_DB


def connect(path: Path = WORKING_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def copy_db(src: Path, dst: Path) -> None:
    """Copy one SQLite file over another using SQLite's backup API, which is
    safe even if the app has the destination open (a plain file copy isn't)."""
    s, d = sqlite3.connect(src), sqlite3.connect(dst)
    try:
        s.backup(d)
    finally:
        s.close()
        d.close()


def ensure_working_db() -> None:
    """Create the working copy from the original if it's missing (fresh deploy)."""
    if not WORKING_DB.exists():
        if not ORIGINAL_DB.exists():
            raise RuntimeError(f"{ORIGINAL_DB.name} not found. Build it with: python -m app.db.seed")
        copy_db(ORIGINAL_DB, WORKING_DB)


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}

"""SQLite access for HomeBase Fit.

Two files, same pattern as the shop project:
  homebase_original.db  clean schema + seeded content (built by seed.py, committed to git)
  homebase.db           working copy the app reads and writes (reset.py restores it). Locally it lives next to
                        the original; in production HOMEBASE_DB_PATH puts it on Render's persistent disk
                        (/var/data/homebase.db, see render.yaml) so accounts survive redeploys.
"""

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import config


def connect(path: Path | None = None) -> sqlite3.Connection:
    # config.WORKING_DB is read at call time so tests can point it at a temp copy.
    # check_same_thread=False: FastAPI may open a request's connection (the `db` dependency) on one worker
    # thread and run the endpoint on another. Each request has its own connection and uses it one step at a
    # time, so handing it between threads is safe.
    conn = sqlite3.connect(path or config.WORKING_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def connect_readonly(path: Path | None = None) -> sqlite3.Connection:
    """A connection that SQLite itself refuses to write through (mode=ro). The MCP tools use
    this, so "read-only" holds even if a query is ever written wrongly."""
    path = path or config.WORKING_DB
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}. Build it with: python -m app.db.seed")
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
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


log = logging.getLogger(__name__)
META_KEY = "original_sha256"
KEEP_BACKUPS = 3


def original_fingerprint() -> str:
    """sha256 of homebase_original.db: changes whenever a deploy ships new content or a new schema."""
    return hashlib.sha256(config.ORIGINAL_DB.read_bytes()).hexdigest()


def stamp_working_db(path: Path | None = None) -> None:
    """Record which original the working copy now matches."""
    conn = connect(path)
    try:
        with conn:
            conn.execute("INSERT INTO app_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = "
                         "excluded.value", (META_KEY, original_fingerprint()))
    finally:
        conn.close()


def working_db_stamp(path: Path | None = None) -> str | None:
    try:
        conn = connect_readonly(path)
    except FileNotFoundError:
        return None
    try:
        row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (META_KEY,)).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:   # a working copy from before app_meta existed
        return None
    finally:
        conn.close()


def _backup_before_refresh() -> Path:
    """A copy of the working DB next to it (on the persistent disk in production), keeping the last few."""
    db = config.WORKING_DB
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = db.with_name(f"{db.stem}.before-refresh-{stamp}{db.suffix}")
    copy_db(db, backup)
    old = sorted(db.parent.glob(f"{db.stem}.before-refresh-*{db.suffix}"))
    for extra in old[:-KEEP_BACKUPS]:
        extra.unlink(missing_ok=True)
    return backup


def ensure_working_db() -> str:
    """Run at startup. Returns what it did:
      "created"    no working copy yet (a brand-new persistent disk, or a fresh local checkout): build it from the
                   clean original, exactly as before, just at config.WORKING_DB.
      "unchanged"  the working copy matches this deploy's original: leave every byte of user data alone.
      "refreshed"  this deploy ships a new original (new content or schema): back the working copy up next to it,
                   then refresh it with the account-keeping refresh (the same one `python -m app.db.seed` runs), so
                   the code and the database schema always match and nobody loses their account.
    """
    if not config.ORIGINAL_DB.exists():
        raise RuntimeError(f"{config.ORIGINAL_DB.name} not found. Build it with: python -m app.db.seed")
    if not config.WORKING_DB.exists():
        config.WORKING_DB.parent.mkdir(parents=True, exist_ok=True)
        copy_db(config.ORIGINAL_DB, config.WORKING_DB)
        stamp_working_db()
        log.info("Created %s from %s.", config.WORKING_DB, config.ORIGINAL_DB.name)
        return "created"
    if working_db_stamp() == original_fingerprint():
        return "unchanged"
    from app.db.reset import refresh_content   # local import: reset imports this module
    backup = _backup_before_refresh()
    result = refresh_content()
    log.warning("New content/schema in %s: refreshed %s, keeping accounts (kept %s, dropped %s). Backup: %s",
                config.ORIGINAL_DB.name, config.WORKING_DB, result["kept"], result["dropped"], backup)
    return "refreshed"


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}

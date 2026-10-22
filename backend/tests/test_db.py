"""Database connection behavior the web server relies on."""

import threading

from app.db import connect


def test_a_request_connection_can_be_used_on_another_thread(test_db):
    """FastAPI can open a request's connection (the `db` dependency) on one worker thread and run the
    endpoint on another. That used to fail with sqlite3.ProgrammingError in the real server."""
    conn = connect()
    result, errors = [], []

    def use_it():
        try:
            result.append(conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0])
        except Exception as e:   # noqa: BLE001 - record any failure for the assertion below
            errors.append(e)

    t = threading.Thread(target=use_it)
    t.start()
    t.join()
    conn.close()
    assert not errors and result == [903]

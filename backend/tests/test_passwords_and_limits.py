"""Username / password accounts in Postgres: they persist, passwords are hashed with Argon2 (old scrypt hashes still
work and are upgraded on sign-in), and sign-in / sign-up are rate limited.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_passwords_and_limits.py -v
"""

import hashlib
import os

import psycopg

from app.db import close_pools, connect
from app.security import hash_password, verify_and_update, verify_password

PASSWORD = "correct horse 1"


def sign_up(client, username, password=PASSWORD):
    return client.post("/api/users", json={"username": username, "first_name": "Pat", "password": password})


def log_in(client, username, password=PASSWORD):
    return client.post("/api/login", json={"username": username, "password": password})


def stored_hash(username):
    conn = connect()
    try:
        return conn.execute("SELECT password_hash FROM users WHERE username = ?", (username,)).fetchone()[0]
    finally:
        conn.close()


def old_scrypt_hash(password):
    """Exactly the format app/security.py wrote before Argon2 (2026-10-25)."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=64)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"


def test_a_password_account_is_really_in_postgres(client, test_db):
    """Sign up through the API, then look with a brand-new connection that has nothing to do with the app's pool:
    the row is committed in Postgres, with an Argon2id hash (never the password)."""
    r = sign_up(client, "persisted_pat")
    assert r.status_code == 201
    uid = r.json()["user_id"]
    close_pools()                                                           # drop every pooled connection
    with psycopg.connect(test_db) as raw:
        row = raw.execute("SELECT id, username::text, first_name, password_hash, email, created_at "
                          "FROM users WHERE id = %s", (uid,)).fetchone()
        assert raw.execute("SELECT pg_typeof(username)::text FROM users WHERE id = %s", (uid,)).fetchone() == ("citext",)
    assert row[:3] == (uid, "persisted_pat", "Pat") and row[4] is None
    assert row[3].startswith("$argon2id$") and PASSWORD not in row[3]
    assert row[5].endswith("Z")                                             # UTC timestamp, same format as before
    login = log_in(client, "PERSISTED_PAT")                                 # and it signs in again (any case)
    assert login.status_code == 200 and login.json()["user_id"] == uid


def test_argon2_hashes_are_salted_and_verify():
    a, b = hash_password(PASSWORD), hash_password(PASSWORD)
    assert a != b and a.startswith("$argon2id$")
    assert verify_password(PASSWORD, a) and not verify_password("wrong password", a)
    assert verify_and_update(PASSWORD, a) == (True, None)                   # up to date: nothing to store
    assert verify_and_update(PASSWORD, None) == (False, None)                # no password (Google / Microsoft only)
    assert verify_and_update(PASSWORD, "garbage") == (False, None)           # never a 500


def test_an_old_scrypt_password_still_works_and_is_upgraded_to_argon2(client):
    sign_up(client, "legacy_lee", password="temporary pass")
    conn = connect()
    with conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE username = 'legacy_lee'", (old_scrypt_hash(PASSWORD),))
    conn.close()
    assert verify_password(PASSWORD, stored_hash("legacy_lee"))

    assert log_in(client, "legacy_lee", "wrong password").status_code == 401
    assert stored_hash("legacy_lee").startswith("scrypt$")                   # a failed sign-in changes nothing
    assert log_in(client, "legacy_lee").status_code == 200
    upgraded = stored_hash("legacy_lee")
    assert upgraded.startswith("$argon2id$") and verify_password(PASSWORD, upgraded)
    assert log_in(client, "legacy_lee").status_code == 200                  # and it keeps working


def test_sign_in_is_rate_limited_per_ip(client):
    sign_up(client, "limited_lou")
    codes = [log_in(client, "limited_lou", "wrong password").status_code for _ in range(10)]
    assert codes == [401] * 10
    blocked = log_in(client, "limited_lou")                                 # even the right password, for now
    assert blocked.status_code == 429 and "wait a minute" in blocked.json()["detail"]


def test_sign_up_is_rate_limited_per_ip(client):
    codes = [sign_up(client, f"new_user_{i}").status_code for i in range(6)]
    assert codes == [201] * 5 + [429]
    conn = connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 5
    finally:
        conn.close()

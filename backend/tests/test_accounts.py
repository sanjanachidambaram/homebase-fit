"""Accounts: sign up and sign in with a username (not an email), a first name for the Dashboard greeting, and
accounts made before usernames existed.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_accounts.py -v

The first name's privacy (it never reaches a model) is tested with the other PII checks:
test_agents.py::test_no_agent_ever_sees_the_username_or_first_name, test_privacy_and_safety.py,
test_plan_agent.py, test_workout_review.py and test_mcp_tools.py.
"""

import sqlite3

import pytest

from app import config
from app.db.reset import refresh_content
from app.security import hash_password

PASSWORD = "correct horse 1"


def sign_up(client, username="sarah_k", first_name="Sarah", password=PASSWORD):
    return client.post("/api/users", json={"username": username, "first_name": first_name, "password": password})


def log_in(client, username, password=PASSWORD):
    return client.post("/api/login", json={"username": username, "password": password})


def test_sign_up_and_sign_in_with_a_username(client):
    r = sign_up(client)
    assert r.status_code == 201, r.text
    uid = r.json()["user_id"]
    login = log_in(client, "sarah_k")
    assert login.status_code == 200 and login.json()["user_id"] == uid
    me = client.get(f"/api/users/{uid}", headers={"Authorization": f"Bearer {login.json()['token']}"}).json()
    assert (me["username"], me["first_name"]) == ("sarah_k", "Sarah")
    assert "email" not in me


def test_usernames_are_unique_ignoring_case_and_sign_in_ignores_case(client):
    assert sign_up(client, "Sarah_K").status_code == 201
    dup = sign_up(client, "sarah_k", first_name="Other Sarah")
    assert dup.status_code == 409 and "username is taken" in dup.json()["detail"]
    assert log_in(client, "SARAH_K").status_code == 200
    assert log_in(client, "  sarah_k ").status_code == 200                     # stray spaces are trimmed


def test_wrong_password_or_unknown_username_says_so_without_saying_which(client):
    sign_up(client)
    for username, password in (("sarah_k", "wrong password 1"), ("nobody_here", PASSWORD)):
        r = log_in(client, username, password)
        assert r.status_code == 401 and r.json()["detail"] == "Username or password is incorrect."


@pytest.mark.parametrize("bad", ["ab", "a" * 31, "sarah k", "sarah@example.com", "sarah!", ""])
def test_username_rules(client, bad):
    r = sign_up(client, bad)
    assert r.status_code == 422, (bad, r.text)


def test_first_name_is_required_and_tidied(client):
    assert sign_up(client, "no_name", first_name="   ").status_code == 422
    assert sign_up(client, "no_name2", first_name="x" * 51).status_code == 422
    assert client.post("/api/users", json={"username": "no_name3", "password": PASSWORD}).status_code == 422
    r = sign_up(client, "tidy", first_name="  Mary \n Ann ").json()
    me = client.get(f"/api/users/{r['user_id']}", headers={"Authorization": f"Bearer {r['token']}"}).json()
    assert me["first_name"] == "Mary Ann"


def test_accounts_from_before_usernames_keep_signing_in_with_their_old_email(client):
    """The working DB on Render's disk (and anyone's local one) has users with an email column. The first start
    with the new schema refreshes it (app.db.ensure_working_db): the old email becomes the username, so the same
    sign-in keeps working, and their data stays. They have no first name yet (the greeting falls back)."""
    conn = sqlite3.connect(config.WORKING_DB)
    with conn:                                                                  # make it look like the old schema
        conn.execute("ALTER TABLE users RENAME COLUMN username TO email")
        conn.execute("ALTER TABLE users DROP COLUMN first_name")
        uid = conn.execute("INSERT INTO users (email, password_hash) VALUES ('old.timer@example.com', ?)",
                           (hash_password(PASSWORD),)).lastrowid
        conn.execute("INSERT INTO exercise_favorites (user_id, exercise_id) VALUES (?, 'glute_bridge')", (uid,))
    conn.close()

    result = refresh_content()
    assert result["kept"]["users"] == 1 and not result["dropped"].get("users")

    login = log_in(client, "Old.Timer@example.com")                             # what they typed before
    assert login.status_code == 200 and login.json()["user_id"] == uid
    h = {"Authorization": f"Bearer {login.json()['token']}"}
    me = client.get(f"/api/users/{uid}", headers=h).json()
    assert (me["username"], me["first_name"]) == ("old.timer@example.com", None)
    assert [f["id"] for f in client.get("/api/favorites", headers=h).json()] == ["glute_bridge"]

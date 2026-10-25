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
from tests.test_calendar import on_day  # noqa: F401  (fixture: freezes the calendar's today)

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


# ---------------------------------------------------------------- "Reset my quiz" (Settings)

def test_reset_my_quiz_goes_back_to_no_plan_and_keeps_what_you_did(client, on_day):
    """on_day freezes 'today' (a Monday), so which days are workouts doesn't depend on when the test runs."""
    from tests.helpers import quiz_answers
    r = sign_up(client, "resetter").json()
    uid, h = r["user_id"], {"Authorization": f"Bearer {r['token']}"}
    assert client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "t", "answers": quiz_answers()}).status_code == 200
    from tests.test_agents import rows
    stored = lambda: [r["id"] for r in rows("SELECT id FROM calendar_entries WHERE user_id = ? ORDER BY date", uid)]
    days = stored()                                                             # four weeks, from today
    assert len(days) == 28
    first_two = rows("SELECT id, day_type FROM calendar_entries WHERE user_id = ? ORDER BY date LIMIT 2", uid)
    workout = next(d for d in first_two if d["day_type"] == "workout")         # today or tomorrow: can be ticked
    done, noted = {"id": workout["id"]}, {"id": next(d["id"] for d in first_two if d["id"] != workout["id"])}
    assert client.patch(f"/api/calendar/{done['id']}", headers=h, json={"completed": True}).status_code == 200
    assert client.patch(f"/api/calendar/{noted['id']}", headers=h, json={"notes": "felt great"}).status_code == 200
    client.post("/api/favorites", headers=h, json={"exercise_id": "glute_bridge"})

    res = client.delete(f"/api/users/{uid}/quiz-profile", headers=h)
    assert res.status_code == 200 and res.json()["reset"] is True and res.json()["calendar_days_cleared"] == len(days) - 2
    me = client.get(f"/api/users/{uid}", headers=h)
    assert me.status_code == 200 and me.json()["quiz_profile"] is None          # still signed in, no quiz
    assert client.get("/api/plan", headers=h).status_code == 409                 # "take the quiz" state
    assert set(stored()) == {done["id"], noted["id"]}                                     # what you did and wrote stays
    assert [f["id"] for f in client.get("/api/favorites", headers=h).json()] == ["glute_bridge"]

    # Retaking later works as normal (the disclaimer is asked again) and lays the calendar out again.
    assert client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "t", "answers": quiz_answers()}).status_code == 200
    assert len(stored()) == 28 and {done["id"], noted["id"]} <= set(stored())


def test_only_you_can_reset_your_quiz(client):
    a = sign_up(client, "owner_a").json()
    b = sign_up(client, "owner_b").json()
    r = client.delete(f"/api/users/{a['user_id']}/quiz-profile", headers={"Authorization": f"Bearer {b['token']}"})
    assert r.status_code == 403
    assert client.delete(f"/api/users/{a['user_id']}/quiz-profile").status_code == 401


# ---------------------------------------------------------------- the 2026-10-25 quiz rewrite: old profiles carried over

@pytest.mark.parametrize("old_goals, goal", [
    (["weight_loss", "rehab"], "lose_weight"), (["strength"], "stronger"), (["tone"], "stronger"),
    (["rehab"], "feel_good"), (["general_health"], "feel_good"), ([], "feel_good"),
])
def test_old_quiz_profiles_are_carried_over_not_dropped(old_goals, goal):
    """On deploy, profiles saved under the old quiz are migrated (app/db/reset.py, migrate_quiz_profile): one goal,
    weight kept only for losing weight (the new schema refuses it otherwise), only equipment the quiz still offers,
    bodyweight always in, review swaps cleared, removed answers dropped."""
    import json
    from app.db.reset import migrate_quiz_profile
    old = {"user_id": 7, "goals": json.dumps(old_goals), "timeline": "8_weeks", "age": 30, "weight": 150.0,
           "height": 64.0, "goal_weight": 140.0, "goal_date": "2026-12-01", "days_available": 3,
           "equipment": json.dumps(["mat", "bench", "pull_up_bar", "dumbbells"]), "plan_swaps": '{"a": "b"}',
           "plan_reviewed": 1, "experience_level": "beginner"}
    new = migrate_quiz_profile(old)
    assert new["goal"] == goal
    assert (new["weight"], new["goal_weight"]) == ((150.0, 140.0) if goal == "lose_weight" else (None, None))
    assert json.loads(new["equipment"]) == ["bodyweight", "dumbbells", "mat"]
    assert (new["plan_swaps"], new["plan_reviewed"]) == ("{}", 0)
    assert migrate_quiz_profile(new) == new                       # a new-style row passes through unchanged

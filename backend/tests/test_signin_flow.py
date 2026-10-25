"""Bug 2026-10-22: "signed up, took the quiz, submitted it, and was immediately signed out; sign-in stopped working".

What actually happened (from the server log): the account was created and the quiz saved fine (200). Then the
content database was rebuilt with `python -m app.db.seed` while that person was still signed in. The seed used to
reset the working database, which deleted every account. Their next request hit a missing user: a workout build
crashed with a 500 (the token log's foreign key), the next one got 401, the app signed them out, and signing back
in failed because the account no longer existed.

These tests pin the whole path down:
  * sign up -> full quiz -> plan -> calendar, with the same sign-in working at every step (all three
    pregnancy answers);
  * running the real seed command mid-session keeps the account, its data, and its sign-in;
  * a calendar failure during quiz save doesn't fail the save (or touch the sign-in);
  * an account that disappears while the AI is running doesn't turn into a 500.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_signin_flow.py -v
"""

from datetime import timedelta

import pytest

from app import calendar, config
from app.db import copy_db
from tests.helpers import quiz_answers
from tests.test_agents import rows, use_script  # noqa: F401  (use_script is a fixture)

PASSWORD = "correct horse 1"


def sign_up(client, username) -> tuple[int, dict]:
    r = client.post("/api/users", json={"username": username, "first_name": "Tester", "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()["user_id"], {"Authorization": f"Bearer {r.json()['token']}"}


def submit_quiz(client, uid, h, **answers):
    return client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "2026-10-22", "answers": quiz_answers(**answers)})


def assert_signed_in(client, uid, h, username):
    """The same token still works everywhere a signed-in page calls, and the password still signs in."""
    me = client.get(f"/api/users/{uid}", headers=h)
    assert me.status_code == 200, me.text
    for path in ("/api/favorites", "/api/calendar", "/api/plan"):
        assert client.get(path, headers=h).status_code == 200, path
    login = client.post("/api/login", json={"username": username, "password": PASSWORD})
    assert login.status_code == 200 and login.json()["user_id"] == uid
    return me.json()


# ---------------------------------------------------------------- the happy path, end to end

@pytest.mark.parametrize("pregnancy", ["none", "pregnant", "postpartum"])
def test_sign_up_quiz_plan_calendar_and_still_signed_in(client, pregnancy):
    username = f"flow-{pregnancy}"
    uid, h = sign_up(client, username)
    assert client.get(f"/api/users/{uid}", headers=h).status_code == 200
    assert client.get("/api/plan", headers=h).status_code == 409       # no quiz yet

    r = submit_quiz(client, uid, h, pregnancy_status=pregnancy)
    assert r.status_code == 200, r.text
    assert r.json()["needs_clinical_review"] is (pregnancy != "none")

    me = assert_signed_in(client, uid, h, username)
    assert me["quiz_profile"]["pregnancy_status"] == pregnancy
    plan = client.get("/api/plan", headers=h).json()
    cal = client.get("/api/calendar", headers=h).json()
    stored = rows("SELECT COUNT(*) AS n FROM calendar_entries WHERE user_id = ?", uid)[0]["n"]
    if pregnancy == "none":
        assert plan["generated"] is True and plan["training_days"] == 4
        assert stored == 28 and cal["needs_clinical_review"] is False and cal["entries"]
    else:
        assert plan["generated"] is False and plan["needs_clinical_review"] is True
        assert stored == 0 and cal["needs_clinical_review"] is True and cal["entries"] == []

    assert submit_quiz(client, uid, h, pregnancy_status=pregnancy, goal="stronger").status_code == 200   # retake
    assert_signed_in(client, uid, h, username)


# ---------------------------------------------------------------- the actual incident: a content rebuild mid-session

@pytest.fixture
def private_original(tmp_path, monkeypatch):
    """Let the seed build its original into a temp file, never over the real homebase_original.db."""
    original = tmp_path / "original.db"
    copy_db(config.ORIGINAL_DB, original)
    monkeypatch.setattr(config, "ORIGINAL_DB", original)
    return original


def test_running_the_seed_mid_session_keeps_the_user_signed_in(client, private_original):
    from app.db.seed import main as seed_main

    username = "live-session"
    uid, h = sign_up(client, username)
    assert submit_quiz(client, uid, h).status_code == 200
    days = {e["date"]: e for e in client.get("/api/calendar", headers=h).json()["entries"]}
    first = days[min(days)]
    client.patch(f"/api/calendar/{first['id']}", headers=h, json={"notes": "my note"})
    client.post("/api/favorites", headers=h, json={"exercise_id": "glute_bridge"})
    before = {t: rows(f"SELECT * FROM {t} WHERE user_id = ? ORDER BY id", uid)
              for t in ("quiz_profiles", "calendar_entries", "exercise_favorites")}

    summary = seed_main([])                     # exactly what was run during the incident: python -m app.db.seed

    assert summary["kept"]["users"] == 1 and not any(summary["dropped"].values())
    assert_signed_in(client, uid, h, username)     # same token, same password
    for table, old in before.items():
        assert rows(f"SELECT * FROM {table} WHERE user_id = ? ORDER BY id", uid) == old, table
    assert submit_quiz(client, uid, h, experience_level="advanced").status_code == 200


def test_wiping_users_is_now_explicit(client, private_original):
    from app.db.seed import main as seed_main

    uid, h = sign_up(client, "demo-wipe")
    seed_main(["--wipe-users"])                 # the old behavior, only on purpose
    assert rows("SELECT COUNT(*) AS n FROM users") == [{"n": 0}]
    assert client.get(f"/api/users/{uid}", headers=h).status_code == 404   # the frontend treats this as signed out


# ---------------------------------------------------------------- the quiz save can't be taken down by the calendar

def test_quiz_save_survives_a_calendar_failure(client):
    def broken(*a, **k):
        raise RuntimeError("calendar exploded")
    username = "calendar-down"
    uid, h = sign_up(client, username)

    with pytest.MonkeyPatch.context() as mp:                              # only the calendar breaks
        mp.setattr(calendar, "materialize_plan", broken)
        r = submit_quiz(client, uid, h)
    assert r.status_code == 200, r.text                                   # the answers are saved...
    assert rows("SELECT COUNT(*) AS n FROM calendar_entries WHERE user_id = ?", uid) == [{"n": 0}]

    # ...and once the calendar works again,
    me = assert_signed_in(client, uid, h, username)                          # the user is still signed in,
    assert me["quiz_profile"]["goal"] == "lose_weight"
    start = calendar.today()                                              # and viewing the calendar lays it out
    shown = client.get("/api/calendar", headers=h, params={"start": start.isoformat(),
                                                           "end": (start + timedelta(days=27)).isoformat()}).json()
    assert len(shown["entries"]) == 28
    assert rows("SELECT COUNT(*) AS n FROM calendar_entries WHERE user_id = ?", uid) == [{"n": 28}]


# ---------------------------------------------------------------- an account deleted while the AI runs

def test_account_deleted_during_an_agent_call_is_not_a_500(client, monkeypatch, use_script):
    from app.agents import harness
    from app.db import connect

    uid, h = sign_up(client, "vanishing")
    assert submit_quiz(client, uid, h, injuries=["none"]).status_code == 200
    script = use_script(("final", {"items": [{"exercise_id": "dead_bug", "sets": 2, "reps": "8", "rest_seconds": 30}],
                                   "balance_note": "-"}))
    real_model = script.model

    def model_that_deletes_the_user():
        conn = connect()
        with conn:                          # the account vanishes mid-request, like the content rebuild did
            for t in ("calendar_entries", "quiz_profiles", "users"):
                conn.execute(f"DELETE FROM {t} WHERE {'id' if t == 'users' else 'user_id'} = ?", (uid,))
        conn.close()
        return real_model()
    monkeypatch.setattr(harness, "get_model", model_that_deletes_the_user)

    r = client.post("/api/workouts/build", headers=h, json={"picks": {"core": 1}, "time_budget_minutes": 10})
    assert r.status_code != 500, r.text
    assert rows("SELECT user_id FROM agent_runs") == [{"user_id": None}]  # tokens still logged, link cut
    assert client.get(f"/api/users/{uid}", headers=h).status_code == 404  # and now they're really signed out

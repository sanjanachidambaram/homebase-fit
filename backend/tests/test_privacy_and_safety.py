"""Consent gate, full data deletion, citation/status fields, and the agent PII boundary.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest -v

Each test runs against a throwaway copy of homebase_original.db, never the real working DB.
"""

import json
import sqlite3

import pytest

from app import config
from app.db import connect
from tests.helpers import quiz_answers

ANSWERS = quiz_answers()
USER_TABLES = ("quiz_profiles", "workout_logs", "measurements", "safety_events", "exercise_favorites",
               "calendar_entries", "cardio_logs", "built_workouts")


def sign_up(client, username, first_name="Tester"):
    r = client.post("/api/users", json={"username": username, "first_name": first_name, "password": "correct horse 1"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["user_id"], {"Authorization": f"Bearer {body['token']}"}


def submit_quiz(client, uid, headers, consent=True):
    return client.put(f"/api/users/{uid}/quiz-profile", headers=headers,
                      json={"consent_accepted": consent, "consent_version": "2026-10-22", "answers": ANSWERS})


def count(table, uid):
    conn = connect()
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (uid,)).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------- consent

def test_quiz_rejected_without_consent(client):
    uid, h = sign_up(client, "user_a")
    r = submit_quiz(client, uid, h, consent=False)
    assert r.status_code == 422
    assert "disclaimer" in r.json()["detail"]
    assert count("quiz_profiles", uid) == 0


def test_database_refuses_profile_without_consent(client):
    uid, _ = sign_up(client, "user_a")
    conn = connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO quiz_profiles (user_id, consent_accepted) VALUES (?, 0)", (uid,))
    conn.close()


def test_quiz_saved_with_consent_timestamp(client):
    uid, h = sign_up(client, "user_a")
    r = submit_quiz(client, uid, h)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["consent_accepted"] is True
    assert p["consent_accepted_at"].endswith("Z")
    assert p["consent_version"] == "2026-10-22"
    assert p["injury_flags"] == ["lower_back"]


def test_password_is_hashed(client):
    sign_up(client, "user_a")
    conn = connect()
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()
    assert stored.startswith("scrypt$") and "correct horse" not in stored


# ---------------------------------------------------------------- deletion

def test_delete_removes_user_and_all_related_rows(client):
    a, ha = sign_up(client, "user_a")
    b, hb = sign_up(client, "user_b")
    for uid, h in ((a, ha), (b, hb)):
        assert submit_quiz(client, uid, h).status_code == 200
    conn = connect()
    with conn:
        for uid in (a, b):
            conn.execute("INSERT INTO workout_logs (user_id, date, exercise_id, sets, reps) "
                         "VALUES (?, '2026-10-20', 'glute_bridge', 3, 12)", (uid,))
            conn.execute("INSERT INTO workout_logs (user_id, date, duration_seconds) VALUES (?, '2026-10-21', 1200)", (uid,))
            conn.execute("INSERT INTO measurements (user_id, date, body_weight) VALUES (?, '2026-10-20', 165)", (uid,))
            conn.execute("INSERT INTO exercise_favorites (user_id, exercise_id) VALUES (?, 'glute_bridge')", (uid,))
            conn.execute("INSERT INTO safety_events (user_id, source, trigger_text, action_taken) "
                         "VALUES (?, 'basics_qa', 'sharp pain in my back', 'redirected_to_professional')", (uid,))
            conn.execute("UPDATE calendar_entries SET notes = 'my own words' WHERE user_id = ? AND date = "
                         "(SELECT MIN(date) FROM calendar_entries WHERE user_id = ?)", (uid, uid))
            conn.execute("INSERT INTO cardio_logs (user_id, date, activity, duration_minutes) "
                         "VALUES (?, '2026-10-20', 'ran 20 min', 20)", (uid,))
            conn.execute("INSERT INTO built_workouts (user_id, request, session) VALUES (?, '{}', '{}')", (uid,))
    conn.close()
    assert count("calendar_entries", a) == 28      # saving the quiz laid out 4 weeks of plan days

    assert client.delete(f"/api/users/{a}").status_code == 401          # no token
    assert client.delete(f"/api/users/{a}", headers=hb).status_code == 403  # someone else's token
    r = client.delete(f"/api/users/{a}", headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["rows_removed"] == {"safety_events": 1, "measurements": 1, "workout_logs": 2,
                                        "calendar_entries": 28, "cardio_logs": 1, "built_workouts": 1,
                                        "exercise_favorites": 1, "quiz_profiles": 1, "users": 1}
    assert len(USER_TABLES) == 8 and set(USER_TABLES) | {"users"} == set(r.json()["rows_removed"])

    for table in USER_TABLES:
        assert count(table, a) == 0, table
        assert count(table, b) >= 1, f"{table}: other user's data must be untouched"
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (a,)).fetchone()[0] == 0
    conn.close()
    assert client.get(f"/api/users/{a}", headers=ha).status_code == 404  # old token is useless now


# ---------------------------------------------------------------- citations / status

def test_schema_has_citations_and_status():
    conn = sqlite3.connect(config.ORIGINAL_DB)
    for table in ("goal_protocols", "exercises"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert {"citations", "status"} <= cols, table
    conn.close()


def test_seed_rejects_pt_reviewed_without_citation():
    from app.db.seed import review_fields
    errors: list[str] = []
    assert review_fields({"status": "pt_reviewed", "citations": []}, "x", errors) is None
    assert "needs at least one citation" in errors[0]
    ok = review_fields({"status": "pt_reviewed", "citations": [{"claim": "c", "source": "s"}]}, "x", [])
    assert ok == ("pt_reviewed", json.dumps([{"claim": "c", "source": "s"}]))


# ---------------------------------------------------------------- PII boundary

def test_agent_profile_contains_no_pii(client):
    from app.agents.context import EXCLUDED_USER_FIELDS, AgentUserProfile, agent_profile_for
    assert set(AgentUserProfile.model_fields) == {"goal", "injury_flags"}       # since 2026-10-25: no weight, age, height
    assert {"username", "first_name", "email", "weight", "goal_weight"} <= EXCLUDED_USER_FIELDS
    assert not set(AgentUserProfile.model_fields) & EXCLUDED_USER_FIELDS
    uid, h = sign_up(client, "private.person", first_name="Zenobia")
    assert client.get(f"/api/users/{uid}", headers=h).json()["first_name"] == "Zenobia"   # stored, for the greeting
    client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "2026-10-22", "answers": ANSWERS,
        "injury_notes": "Dr. Smith said L4 disc issue"})
    prompt = agent_profile_for(uid).to_prompt_json()
    for secret in ("private.person", "Zenobia", "Dr. Smith", "L4", str(uid) + ",", "165", "155", '"weight', "goal_weight"):
        assert secret not in prompt
    assert json.loads(prompt)["injury_flags"] == ["lower_back"]


def test_the_free_text_box_is_gone_and_nothing_is_stored(client):
    """The "Anything else we should know?" box was removed (2026-10-25): no question, no column. An old client that
    still sends injury_notes is ignored, and the text is stored nowhere."""
    from app.db import connect
    qs = client.get("/api/quiz/questions").json()
    assert not any(q.get("allow_free_text") or q.get("free_text_prompt") for q in qs)
    uid, h = sign_up(client, "notes.person")
    r = client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "2026-10-22", "answers": ANSWERS,
        "injury_notes": "SENT-ANYWAY Dr. Smith"})
    assert r.status_code == 200 and "injury_notes" not in r.json()
    conn = connect()
    try:
        assert "injury_notes" not in {c["name"] for c in conn.execute("PRAGMA table_info(quiz_profiles)")}
        row = dict(conn.execute("SELECT * FROM quiz_profiles WHERE user_id = ?", (uid,)).fetchone())
    finally:
        conn.close()
    assert "SENT-ANYWAY" not in json.dumps(row)

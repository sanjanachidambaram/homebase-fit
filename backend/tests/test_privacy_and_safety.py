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

ANSWERS = {"goals": ["weight_loss", "rehab"], "timeline": "8_weeks", "injuries": ["lower_back"],
           "age": 34, "weight": 165, "height": 66}
USER_TABLES = ("quiz_profiles", "workout_logs", "measurements", "safety_events", "exercise_favorites")


def sign_up(client, email):
    r = client.post("/api/users", json={"email": email, "password": "correct horse 1"})
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
    uid, h = sign_up(client, "a@example.com")
    r = submit_quiz(client, uid, h, consent=False)
    assert r.status_code == 422
    assert "disclaimer" in r.json()["detail"]
    assert count("quiz_profiles", uid) == 0


def test_database_refuses_profile_without_consent(client):
    uid, _ = sign_up(client, "a@example.com")
    conn = connect()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO quiz_profiles (user_id, consent_accepted) VALUES (?, 0)", (uid,))
    conn.close()


def test_quiz_saved_with_consent_timestamp(client):
    uid, h = sign_up(client, "a@example.com")
    r = submit_quiz(client, uid, h)
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["consent_accepted"] is True
    assert p["consent_accepted_at"].endswith("Z")
    assert p["consent_version"] == "2026-10-22"
    assert p["injury_flags"] == ["lower_back"]


def test_password_is_hashed(client):
    sign_up(client, "a@example.com")
    conn = connect()
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()
    assert stored.startswith("scrypt$") and "correct horse" not in stored


# ---------------------------------------------------------------- deletion

def test_delete_removes_user_and_all_related_rows(client):
    a, ha = sign_up(client, "a@example.com")
    b, hb = sign_up(client, "b@example.com")
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
    conn.close()

    assert client.delete(f"/api/users/{a}").status_code == 401          # no token
    assert client.delete(f"/api/users/{a}", headers=hb).status_code == 403  # someone else's token
    r = client.delete(f"/api/users/{a}", headers=ha)
    assert r.status_code == 200, r.text
    assert r.json()["rows_removed"] == {"safety_events": 1, "measurements": 1, "workout_logs": 2,
                                        "exercise_favorites": 1, "quiz_profiles": 1, "users": 1}

    for table in USER_TABLES:
        assert count(table, a) == 0, table
        assert count(table, b) >= 1, f"{table}: other user's data must be untouched"
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (a,)).fetchone()[0] == 0
    conn.close()
    assert client.get(f"/api/users/{a}", headers=ha).status_code == 404  # old token is useless now


# ---------------------------------------------------------------- citations / status

@pytest.mark.parametrize("route", ["/api/programs", "/api/basics"])
def test_placeholder_content_flagged_with_citations_field(client, route):
    items = client.get(route).json()
    assert items
    for item in items:
        assert item["status"] == "placeholder"
        assert item["review_notice"] == "Content pending expert review"
        assert item["citations"] == []


def test_schema_has_citations_and_status():
    conn = sqlite3.connect(config.ORIGINAL_DB)
    for table in ("program_templates", "basics_articles"):
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
    from app.agents.context import AgentUserProfile, agent_profile_for
    assert set(AgentUserProfile.model_fields) == {"goals", "timeline", "injury_flags", "age", "weight_lb", "height_in"}
    uid, h = sign_up(client, "private.person@example.com")
    client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "2026-10-22", "answers": ANSWERS,
        "injury_notes": "Dr. Smith said L4 disc issue"})
    prompt = agent_profile_for(uid).to_prompt_json()
    for secret in ("private.person", "example.com", "Dr. Smith", "L4", str(uid) + ","):
        assert secret not in prompt
    assert json.loads(prompt)["injury_flags"] == ["lower_back"]

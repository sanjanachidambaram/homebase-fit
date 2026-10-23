"""Cardio logging: a log, not a recommendation. No AI, the same red-flag check as notes, private like notes, and
open to pregnant / postpartum users in their own words (shared_rules.md rule 9).

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_cardio.py -v
"""

from datetime import timedelta

import pytest

from app.agents import harness
from app.cardio import CARDIO_SUPPORT_MESSAGE, CARDIO_SUPPORT_PREGNANCY
from tests.test_agents import rows, use_script  # noqa: F401  (fixture)
from tests.test_calendar import MONDAY, Recorder, account, by_date, d, get_days, on_day, retake  # noqa: F401

SENTINEL = "PRIVATE-CARDIO-TEXT-4417"


def log(client, h, **body):
    return client.post("/api/cardio", headers=h, json={"date": d(1), "duration_minutes": 20, **body})


def test_the_library_has_real_cardio_exercises(client):
    ex = client.get("/api/cardio/exercises").json()
    names = {e["name"] for e in ex}
    assert len(ex) == 14 and {"Rope Jumping", "Walking, Treadmill", "Trail Running/Walking"} <= names


def test_free_text_cardio_on_a_rest_day_is_saved_and_counts_as_activity(client, on_day, use_script):
    script = use_script(("final", {"encouragement": "x", "fun_fact_comparison": None}))
    uid, h = account(client, "cardio@example.com")
    assert by_date(get_days(client, h))[d(1)]["day_type"] == "rest"
    r = log(client, h, activity="ran 20 min around the park")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["log"]["activity"] == "ran 20 min around the park" and body["safety"] == {"flagged": False}
    assert body["agent_called"] is False and script.calls == 0 and rows("SELECT COUNT(*) AS n FROM agent_runs") == [{"n": 0}]
    logged = rows("SELECT date, exercise_id, duration_seconds, notes, cardio_log_id FROM workout_logs WHERE user_id = ?", uid)
    assert logged == [{"date": d(1), "exercise_id": None, "duration_seconds": 1200, "notes": None,
                       "cardio_log_id": body["log"]["id"]}]                       # the text is not copied
    assert [c["activity"] for c in get_days(client, h)["cardio"]] == ["ran 20 min around the park"]

    assert client.delete(f"/api/cardio/{body['log']['id']}", headers=h).status_code == 200
    assert rows("SELECT COUNT(*) AS n FROM workout_logs WHERE user_id = ?", uid) == [{"n": 0}]


def test_picking_a_library_cardio_exercise(client, on_day):
    uid, h = account(client, "pick@example.com")
    r = log(client, h, exercise_id="Rope_Jumping", duration_minutes=10)
    assert r.status_code == 201 and r.json()["log"]["exercise_name"] == "Rope Jumping"
    assert rows("SELECT exercise_id, duration_seconds FROM workout_logs WHERE user_id = ?", uid) == [
        {"exercise_id": "Rope_Jumping", "duration_seconds": 600}]
    assert log(client, h, exercise_id="glute_bridge").status_code == 422          # not a cardio exercise
    assert log(client, h).status_code == 422                                      # nothing said, nothing picked
    assert log(client, h, activity="walk", date=d(5)).status_code == 422          # not ahead of time
    assert log(client, h, activity="walk", user_id=1).status_code == 422          # no user_id from the client


def test_red_flag_in_a_cardio_log_is_saved_logged_and_answered_without_ai(client, on_day, use_script):
    script = use_script(("final", {"encouragement": "x", "fun_fact_comparison": None}))
    uid, h = account(client, "cardioflag@example.com")
    text = "ran 3 miles, sharp pain in my knee"
    r = log(client, h, activity=text).json()
    assert r["log"]["activity"] == text and r["safety"]["flagged"] is True
    assert r["safety"]["message"] == CARDIO_SUPPORT_MESSAGE
    assert rows("SELECT source, trigger_text, action_taken FROM safety_events WHERE user_id = ?", uid) == [
        {"source": "cardio_log", "trigger_text": text, "action_taken": "log_saved_pointed_to_professional"}]
    assert script.calls == 0


def test_pregnant_users_can_log_in_their_own_words_only(client, on_day):
    """Decision (shared_rules.md rule 9): yes to free-text logging (it's their own log, no AI, no prescription),
    no to the exercise library (a list of exercises reads as a suggestion while they have no plan)."""
    uid, h = account(client, "expecting@example.com", pregnancy_status="pregnant")
    r = log(client, h, activity="prenatal yoga class", duration_minutes=45)
    assert r.status_code == 201, r.text
    cal = get_days(client, h)
    assert cal["needs_clinical_review"] is True and cal["entries"] == []          # still no plan or workouts
    assert [c["activity"] for c in cal["cardio"]] == ["prenatal yoga class"]      # but their log is there
    picked = log(client, h, exercise_id="Rope_Jumping")
    assert picked.status_code == 403 and picked.json()["detail"]["code"] == "needs_clinical_review"
    flagged = log(client, h, activity="walked, then some bleeding").json()
    assert flagged["safety"]["flagged"] and flagged["safety"]["message"] == CARDIO_SUPPORT_PREGNANCY
    assert "OB-GYN or midwife" in CARDIO_SUPPORT_PREGNANCY


def test_cardio_text_never_reaches_any_model(client, on_day, monkeypatch):
    uid, h = account(client, "cardioprivate@example.com", injuries=["none"])
    assert log(client, h, activity=SENTINEL, date=d(0)).status_code == 201
    sent = []
    for method, route, body, steps in [
        ("GET", "/api/coach/summary", None, [("get_progress_summary", {}), ("check_goal_achievement", {}),
                                              ("final", {"encouragement": "Nice!", "fun_fact_comparison": None})]),
        ("POST", "/api/workouts/build", {"picks": {"core": 1}, "time_budget_minutes": 10},
         [("final", {"items": [], "balance_note": "-"})]),
        ("POST", "/api/programs/recommend", {}, [("final", {"explanation": "A plan."})]),
    ]:
        rec = Recorder(*steps)
        monkeypatch.setattr(harness, "get_model", rec.model)
        client.request(method, route, json=body, headers=h)
        sent += rec.seen
    assert sent and SENTINEL not in " ".join(sent)
    assert "sessions_logged" in " ".join(sent)                                     # the Coach did see the activity count


@pytest.mark.parametrize("who", ["other user"])
def test_only_the_owner_can_delete_a_log(client, on_day, who):
    uid, h = account(client, "owner@example.com")
    other, oh = account(client, "notowner@example.com")
    log_id = log(client, h, activity="swim").json()["log"]["id"]
    assert client.delete(f"/api/cardio/{log_id}", headers=oh).status_code == 404
    assert client.get("/api/cardio", headers=oh, params={"start": d(0), "end": d(6)}).json() == []

"""Pregnant / postpartum users never reach an AI agent, anywhere.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_clinical_review.py -v

Every route that can call the model is tried with a pregnant and a postpartum profile, with a fake model that
counts its calls. The answer must come from code (or a 403 pointing at /pregnancy-support), with zero model calls
and no agent_runs row.
"""

import pytest

from app.safety_rules import CLINICAL_REVIEW_NO_AI, CLINICAL_REVIEW_PAGE
from tests.helpers import quiz_answers
from tests.test_agents import rows, use_script  # noqa: F401  (use_script is a fixture)


def account(client, username, pregnancy_status) -> tuple[int, dict]:
    r = client.post("/api/users", json={"username": username, "first_name": "Tester", "password": "correct horse 1"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    assert client.put(f"/api/users/{r['user_id']}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "test",
        "answers": quiz_answers(pregnancy_status=pregnancy_status)}).status_code == 200
    return r["user_id"], h


def any_model_answer(use_script):
    """A fake model that would happily answer anything, so a zero call count really means it was never asked."""
    return use_script(("final", {"answered": True, "answer": "x", "source_slugs": [], "items": [],
                                 "balance_note": "x", "encouragement": "x", "fun_fact_comparison": "x",
                                 "explanation": "x"}))


@pytest.mark.parametrize("status", ["pregnant", "postpartum"])
def test_no_ai_route_calls_the_model(client, use_script, status):
    script = any_model_answer(use_script)
    uid, h = account(client, f"{status}", status)

    build = client.post("/api/workouts/build", headers=h, json={"picks": {"core": 1}, "time_budget_minutes": 10})
    coach = client.get("/api/coach/summary", headers=h)
    for r in (build, coach):
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == {"code": "needs_clinical_review", "message": CLINICAL_REVIEW_NO_AI,
                                      "page": CLINICAL_REVIEW_PAGE}

    plan = client.post("/api/programs/recommend", headers=h).json()
    assert plan["meta"]["agent_called"] is False and plan["result"]["plan"]["generated"] is False

    assert script.calls == 0
    assert rows("SELECT COUNT(*) AS n FROM agent_runs")[0]["n"] == 0


def test_other_users_are_unaffected(client, use_script):
    use_script(("final", {"explanation": "A plan built around your goal."}))
    uid, h = account(client, "not-pregnant", "none")
    r = client.post("/api/programs/recommend", headers=h).json()
    assert r["result"]["explanation"] == "A plan built around your goal."           # the model answered
    assert rows("SELECT agent_name FROM agent_runs") == [{"agent_name": "program_architect"}]
    assert client.get("/api/coach/summary", headers=h).status_code != 403


def test_changing_the_answer_lifts_the_block(client, use_script):
    any_model_answer(use_script)
    uid, h = account(client, "after", "pregnant")
    assert client.get("/api/coach/summary", headers=h).status_code == 403
    assert client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "test",
        "answers": quiz_answers(pregnancy_status="none")}).status_code == 200
    assert client.get("/api/coach/summary", headers=h).status_code != 403


def test_acog_opinion_is_in_the_sources(client):
    acog = next(s for s in client.get("/api/sources").json() if s["id"] == "acog-co-804")
    assert "804" in acog["name"] and acog["url"].startswith("https://www.acog.org/") and acog["status"] == "active"

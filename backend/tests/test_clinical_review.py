"""Pregnant / postpartum users never reach an AI agent, anywhere.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_clinical_review.py -v

Every route that can call the model is tried with a pregnant and a postpartum profile, with a fake model that
counts its calls. The answer must come from code (or a 403 pointing at /pregnancy-support), with zero model calls
and no agent_runs row. The red-flag safety check still runs first for Basics questions.
"""

import pytest

from app.safety_rules import CLINICAL_REVIEW_NO_AI, CLINICAL_REVIEW_PAGE
from tests.helpers import quiz_answers
from tests.test_agents import RED_FLAG_QUESTION, rows, use_script  # noqa: F401  (use_script is a fixture)

ANSWERABLE = "How long should I rest between sets?"   # has a Basics article, so only the clinical block can stop it


def account(client, email, pregnancy_status) -> tuple[int, dict]:
    r = client.post("/api/users", json={"email": email, "password": "correct horse 1"}).json()
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
    uid, h = account(client, f"{status}@example.com", status)

    build = client.post("/api/workouts/build", headers=h, json={"picks": {"core": 1}, "time_budget_minutes": 10})
    coach = client.get("/api/coach/summary", headers=h)
    for r in (build, coach):
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == {"code": "needs_clinical_review", "message": CLINICAL_REVIEW_NO_AI,
                                      "page": CLINICAL_REVIEW_PAGE}

    ask = client.post("/api/basics/ask", headers=h, json={"question": ANSWERABLE}).json()
    assert ask["result"] == {"answer": CLINICAL_REVIEW_NO_AI, "answered": False, "redirected_to_professional": False,
                             "sources": [], "review_note": None}
    assert ask["meta"] == {"agent_called": False, "needs_clinical_review": True, "page": "/pregnancy-support"}

    plan = client.post("/api/programs/recommend", headers=h).json()
    assert plan["meta"]["agent_called"] is False and plan["result"]["plan"]["generated"] is False

    assert script.calls == 0
    assert rows("SELECT COUNT(*) AS n FROM agent_runs")[0]["n"] == 0


def test_red_flag_check_still_runs_first(client, use_script):
    script = any_model_answer(use_script)
    uid, h = account(client, "rf-pregnant@example.com", "pregnant")
    r = client.post("/api/basics/ask", headers=h, json={"question": RED_FLAG_QUESTION}).json()
    assert r["result"]["redirected_to_professional"] is True and script.calls == 0
    assert rows("SELECT trigger_text FROM safety_events WHERE user_id = ?", uid) == [{"trigger_text": RED_FLAG_QUESTION}]


def test_other_users_are_unaffected(client, use_script):
    use_script(("search_basics_kb", {"query": "rest between sets"}),
               ("final", {"answered": True, "source_slugs": ["rest_between_sets"],
                          "answer": "Our guide says about 60 to 90 seconds for moderate sets."}))
    uid, h = account(client, "not-pregnant@example.com", "none")
    r = client.post("/api/basics/ask", headers=h, json={"question": ANSWERABLE}).json()
    assert r["meta"]["agent_called"] is True and r["result"]["answered"] is True
    assert client.get("/api/coach/summary", headers=h).status_code != 403


def test_changing_the_answer_lifts_the_block(client, use_script):
    any_model_answer(use_script)
    uid, h = account(client, "after@example.com", "pregnant")
    assert client.get("/api/coach/summary", headers=h).status_code == 403
    assert client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "test",
        "answers": quiz_answers(pregnancy_status="none")}).status_code == 200
    assert client.get("/api/coach/summary", headers=h).status_code != 403


def test_acog_opinion_is_in_the_sources(client):
    acog = next(s for s in client.get("/api/sources").json() if s["id"] == "acog-co-804")
    assert "804" in acog["name"] and acog["url"].startswith("https://www.acog.org/") and acog["status"] == "active"

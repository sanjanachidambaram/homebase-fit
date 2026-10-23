"""The simplified Program Architect (explains a generated plan, no tools), the plan routes, and the new quiz fields.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_plan_agent.py -v
"""

from datetime import date, timedelta

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents import harness
from app.db import connect
from tests.helpers import quiz_answers


class Explainer:
    """Fake model: records what it was shown, then answers with the given explanations in turn."""

    def __init__(self, *explanations):
        self.explanations, self.calls, self.prompts, self.tools = list(explanations), 0, [], None

    def model(self):
        def fn(messages, info: AgentInfo):
            self.calls += 1
            self.tools = info.function_tools
            self.prompts += [p.content for m in messages for p in getattr(m, "parts", []) if isinstance(p, UserPromptPart)]
            text = self.explanations[min(self.calls - 1, len(self.explanations) - 1)]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"explanation": text})])
        return FunctionModel(fn)


@pytest.fixture
def explainer(monkeypatch):
    def install(*explanations):
        e = Explainer(*explanations)
        monkeypatch.setattr(harness, "get_model", e.model)
        return e
    return install


def account(client, username="plan", first_name="Tester", **answer_overrides):
    r = client.post("/api/users", json={"username": username, "first_name": first_name, "password": "correct horse 1"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    res = client.put(f"/api/users/{r['user_id']}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "test", "answers": quiz_answers(**answer_overrides),
        "injury_notes": "PRIVATE-NOTE Dr. Smith"})
    assert res.status_code == 200, res.text
    return r["user_id"], h


# ---------------------------------------------------------------- the simplified agent

def test_recommend_returns_the_generated_plan_and_an_explanation(client, explainer):
    e = explainer("A gentle three-day plan built around your weight loss and rehab goals.")
    uid, h = account(client)
    r = client.post("/api/programs/recommend", headers=h)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["explanation"].startswith("A gentle three-day plan")
    plan = res["plan"]
    assert plan["generated"] and plan["training_days"] == 3 and len(plan["days"]) == 7
    assert plan["safety"]["checked_only"] is True and plan["safety"]["injury_flags"] == ["lower_back"]
    assert "pending expert review" in res["review_note"].lower()
    assert e.calls == 1 and e.tools == []          # one model request, and no tools at all


def test_the_model_sees_only_goals_and_the_plan(client, explainer):
    e = explainer("Here's why it fits.")
    uid, h = account(client, username="private.person", first_name="Zenobia", other_activity_notes="PRIVATE-ACTIVITY",
                     goal_weight=150, goal_date=(date.today() + timedelta(days=90)).isoformat())
    client.post("/api/programs/recommend", headers=h)
    shown = " ".join(e.prompts)
    assert '"goals":["rehab","weight_loss"]' in shown and "Glute Bridge" in shown
    for private in ("private.person", "Zenobia", "PRIVATE-NOTE", "Dr. Smith", "PRIVATE-ACTIVITY",
                    '"age"', '"weight"', "150", "pregnan", f'"user_id"'):
        assert private not in shown, private


def test_explanation_cant_claim_science_without_citations(client, explainer):
    explainer("Research proves this plan works.", "A steady, gentle plan with rest days between sessions.")
    uid, h = account(client)
    assert client.post("/api/programs/recommend", headers=h).json()["result"]["explanation"] == \
        "A steady, gentle plan with rest days between sessions."
    explainer("Studies show it's scientifically proven.")             # keeps claiming: plain fallback
    res = client.post("/api/programs/recommend", headers=h).json()["result"]
    assert "pending expert review" in res["explanation"] and "proven" not in res["explanation"].lower()


def test_each_explanation_is_logged_to_agent_runs(client, explainer):
    explainer("Fits your goals.")
    uid, h = account(client)
    meta = client.post("/api/programs/recommend", headers=h).json()["meta"]
    conn = connect()
    run = dict(conn.execute("SELECT * FROM agent_runs WHERE id = ?", (meta["agent_run_id"],)).fetchone())
    conn.close()
    assert (run["agent_name"], run["route"], run["requests"], run["tool_calls"]) == \
        ("program_architect", "POST /api/programs/recommend", 1, 0)


@pytest.mark.parametrize("status", ["pregnant", "postpartum"])
def test_pregnant_or_postpartum_never_calls_the_model(client, explainer, status):
    e = explainer("should not be used")
    uid, h = account(client, pregnancy_status=status)
    res = client.post("/api/programs/recommend", headers=h).json()
    assert e.calls == 0 and res["meta"]["agent_called"] is False
    assert res["result"]["plan"]["generated"] is False and res["result"]["plan"]["needs_clinical_review"] is True
    assert "OB-GYN" in res["result"]["explanation"]


def test_plan_routes_need_a_quiz_and_a_sign_in(client, explainer):
    explainer("x")
    r = client.post("/api/users", json={"username": "noquiz", "first_name": "Tester", "password": "correct horse 1"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    assert client.post("/api/programs/recommend", headers=h).status_code == 409
    assert client.get("/api/plan", headers=h).status_code == 409
    assert client.get("/api/plan").status_code == 401
    assert client.post("/api/programs/recommend", headers=h, json={"user_id": 1}).status_code == 422


def test_get_plan_is_code_only(client, explainer):
    e = explainer("x")
    uid, h = account(client)
    plan = client.get("/api/plan", headers=h).json()
    assert plan["generated"] and e.calls == 0
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0] == 0   # no tokens spent
    conn.close()


# ---------------------------------------------------------------- the new quiz fields

def test_new_quiz_fields_are_saved(client):
    goal_day = (date.today() + timedelta(days=70)).isoformat()
    uid, h = account(client, experience_level="intermediate", days_available=5, session_length="45",
                     equipment=["dumbbells", "bench"], other_activity_days=2, other_activity_notes="  running  ",
                     goal_weight=158, goal_date=goal_day, injuries=["wrist", "ankle"])
    p = client.get(f"/api/users/{uid}", headers=h).json()["quiz_profile"]
    assert (p["experience_level"], p["days_available"], p["session_length_minutes"]) == ("intermediate", 5, 45)
    assert p["equipment"] == ["bench", "dumbbells"] and p["other_activity_days"] == 2
    assert p["other_activity_notes"] == "running" and (p["goal_weight"], p["goal_date"]) == (158, goal_day)
    assert p["injury_flags"] == ["ankle", "wrist"] and p["needs_clinical_review"] is False


@pytest.mark.parametrize("status, flagged", [("none", False), ("pregnant", True), ("postpartum", True)])
def test_pregnancy_answers_are_flagged_for_clinical_review(client, status, flagged):
    uid, h = account(client, username=f"{status}", pregnancy_status=status)
    assert client.get(f"/api/users/{uid}", headers=h).json()["quiz_profile"]["needs_clinical_review"] is flagged


def test_quiz_validation(client):
    r = client.post("/api/users", json={"username": "user_v", "first_name": "Tester", "password": "correct horse 1"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}

    def put(**over):
        return client.put(f"/api/users/{r['user_id']}/quiz-profile", headers=h, json={
            "consent_accepted": True, "consent_version": "t", "answers": quiz_answers(**over)})
    assert put(goal_date="2001-01-01").status_code == 422                  # past
    assert put(goal_date=(date.today() + timedelta(days=365 * 6)).isoformat()).status_code == 422   # too far
    assert put(goal_date="next spring").status_code == 422
    assert put(goals=["bulk"]).status_code == 422
    assert put(days_available=8).status_code == 422
    assert put(other_activity_notes="x" * 501).status_code == 422
    assert put(pregnancy_status=None).status_code == 422                  # required
    assert put(goal_weight=None, goal_date=None).status_code == 200       # the weight goal is optional
    # a retake clears an answer that's now left blank
    put(goal_weight=150)
    put(goal_weight=None)
    assert client.get(f"/api/users/{r['user_id']}", headers=h).json()["quiz_profile"]["goal_weight"] is None


def test_quiz_questions_carry_descriptions_and_the_cited_pace_note(client):
    qs = {q["id"]: q for q in client.get("/api/quiz/questions").json()}
    goals = {o["value"]: o for o in qs["goals"]["options"]}
    assert set(goals) == {"weight_loss", "strength", "tone", "rehab", "general_health"}
    assert all(o.get("description") for o in goals.values())
    assert all(o.get("description") for o in qs["experience_level"]["options"])
    note = qs["goal_weight"]["rate_note"]
    assert note["max_lbs_per_week"] == 2 and "cdc.gov" in note["source"]
    assert qs["goal_date"]["type"] == "date" and not qs["goal_weight"]["required"]
    health = [q for q in qs.values() if q.get("health")]
    assert {"injuries", "pregnancy_status", "goal_weight"} <= {q["id"] for q in health}   # behind the consent gate

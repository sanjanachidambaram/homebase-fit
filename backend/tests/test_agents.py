"""The four agents, their routes, and the guarantees around them.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_agents.py -v
Safety-section evidence (prints the safety_events row the test creates):
    .venv\\Scripts\\python.exe -m pytest tests/test_agents.py -v -s -k red_flag_question_never_reaches_the_agent

No test calls the real model. Each test swaps in a scripted model (PydanticAI's FunctionModel) that plays
the model's part, including deliberately misbehaving, so the code's checks can be tested exactly.
All tests run against a throwaway copy of the database.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents import basics, harness
from app.agents.harness import McpGateway
from app.db import connect
from tests.helpers import quiz_answers

TODAY = datetime.now(timezone.utc).date()
RED_FLAG_QUESTION = "I have a sharp pain in my knee when I squat. Should I keep going?"


# ---------------------------------------------------------------- helpers

class Script:
    """A fake model that plays back fixed steps: ("tool_name", args) or ("final", output)."""

    def __init__(self, *steps):
        self.steps, self.calls, self.tool_defs, self.seen = list(steps), 0, [], []

    def model(self) -> FunctionModel:
        def fn(messages, info: AgentInfo) -> ModelResponse:
            self.calls += 1
            self.tool_defs = info.function_tools
            self.seen.append(repr(messages))     # everything sent: instructions, prompt, tool results
            step = sum(isinstance(m, ModelResponse) for m in messages)
            name, args = self.steps[min(step, len(self.steps) - 1)]
            if name == "final":
                name = info.output_tools[0].name
            return ModelResponse(parts=[ToolCallPart(name, args)])
        return FunctionModel(fn)


@pytest.fixture
def use_script(monkeypatch):
    def install(*steps) -> Script:
        script = Script(*steps)
        monkeypatch.setattr(harness, "get_model", script.model)
        return script
    return install


@pytest.fixture
def mcp_calls(monkeypatch):
    """Records the real arguments of every MCP tool call (what the server actually received)."""
    calls: list[tuple[str, dict]] = []
    original = McpGateway.call

    async def spy(self, tool, args, **kw):
        calls.append((tool, dict(args)))
        return await original(self, tool, args, **kw)
    monkeypatch.setattr(McpGateway, "call", spy)
    return calls


def account(client, username, injuries=("lower_back",), goals=None) -> tuple[int, dict]:
    r = client.post("/api/users", json={"username": username, "first_name": "Tester", "password": "correct horse 1"})
    uid, token = r.json()["user_id"], r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    answers = quiz_answers(injuries=list(injuries) or ["none"], **({"goals": goals} if goals else {}))
    assert client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "test", "answers": answers}).status_code == 200
    return uid, h


def log_days(uid, days, weight=20.0):
    conn = connect()
    with conn:
        for d in days:
            conn.execute("INSERT INTO workout_logs (user_id, date, exercise_id, sets, reps, weight_used) "
                         "VALUES (?, ?, 'glute_bridge', 3, 10, ?)", (uid, (TODAY - timedelta(days=d)).isoformat(), weight))
    conn.close()


def rows(sql, *args):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


# ================================================================ SAFETY: red-flag pre-filter

def test_red_flag_question_never_reaches_the_agent(client, use_script, monkeypatch):
    script = use_script(("final", {"answered": True, "answer": "x", "source_slugs": []}))
    agent_run = AsyncMock(side_effect=AssertionError("the Basics agent must not be called"))
    monkeypatch.setattr(basics.basics_agent, "run", agent_run)
    uid, h = account(client, "safety")

    r = client.post("/api/basics/ask", json={"question": RED_FLAG_QUESTION}, headers=h)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"]["redirected_to_professional"] is True
    assert "doctor or physical therapist" in body["result"]["answer"]
    assert body["meta"]["agent_called"] is False and "sharp/severe pain" in body["meta"]["red_flags"]
    agent_run.assert_not_called()        # the agent's run() was never invoked...
    assert script.calls == 0             # ...and the model was never called
    assert rows("SELECT COUNT(*) AS n FROM agent_runs")[0]["n"] == 0   # no tokens spent

    events = rows("SELECT * FROM safety_events_report")
    assert len(events) == 1
    e = events[0]
    assert (e["source"], e["trigger_text"], e["action_taken"], e["username"]) == \
        ("basics_qa", RED_FLAG_QUESTION, "redirected_to_professional", "safety")
    print("\nsafety_events row created by the red-flag pre-filter:")
    print(json.dumps(rows("SELECT * FROM safety_events WHERE id = ?", body["meta"]["safety_event_id"])[0], indent=2))


@pytest.mark.parametrize("question", [
    "I have numbness in my leg after planks", "I can't move my shoulder since yesterday",
    "Is it okay to work out with chest pain?", "I felt dizzy and almost fainted during squats",
    "I think I tore my hamstring", "my lower back hurts when I bend over", "severe cramps after running",
    "I'm pregnant and noticed some bleeding after a workout", "It hurts when I lift my arm overhead",
])
def test_every_red_flag_redirects_and_logs(client, use_script, question):
    script = use_script(("final", {"answered": True, "answer": "x", "source_slugs": []}))
    uid, h = account(client, "user_rf")
    r = client.post("/api/basics/ask", json={"question": question}, headers=h).json()
    assert r["result"]["redirected_to_professional"] and script.calls == 0
    assert rows("SELECT trigger_text FROM safety_events WHERE user_id = ?", uid) == [{"trigger_text": question}]


def test_ordinary_question_is_answered_from_the_knowledge_base(client, use_script):
    use_script(("search_basics_kb", {"query": "rest between sets"}),
               ("final", {"answered": True, "source_slugs": ["rest_between_sets"],
                          "answer": "Our guide says about 60 to 90 seconds for moderate sets of 8 to 15 reps."}))
    uid, h = account(client, "ask")
    r = client.post("/api/basics/ask", json={"question": "How long should I rest between sets?"}, headers=h).json()
    res = r["result"]
    assert res["answered"] and not res["redirected_to_professional"]
    assert res["sources"][0]["slug"] == "rest_between_sets" and res["sources"][0]["status"] == "placeholder"
    assert res["sources"][0]["review_notice"] == "Content pending expert review" and res["review_note"]
    assert rows("SELECT COUNT(*) AS n FROM safety_events")[0]["n"] == 0


def test_question_with_no_matching_article_never_calls_the_model(client, use_script):
    script = use_script(("final", {"answered": True, "answer": "made up", "source_slugs": []}))
    uid, h = account(client, "nomatch")
    r = client.post("/api/basics/ask", json={"question": "Which protein powder brand is best?"}, headers=h).json()
    assert r["result"]["answer"] == basics.NO_INFO_MESSAGE and script.calls == 0
    assert rows("SELECT COUNT(*) AS n FROM agent_runs")[0]["n"] == 0


def test_basics_rejects_invented_sources_and_science_claims(client, use_script):
    use_script(("search_basics_kb", {"query": "rest between sets"}),
               ("final", {"answered": True, "answer": "Rest 90s.", "source_slugs": ["made_up_article"]}),
               ("final", {"answered": True, "answer": "Research shows 90 seconds is best.",
                          "source_slugs": ["rest_between_sets"]}),
               ("final", {"answered": True, "answer": "Our guide says 60 to 90 seconds for moderate sets.",
                          "source_slugs": ["rest_between_sets"]}))
    uid, h = account(client, "claims")
    res = client.post("/api/basics/ask", json={"question": "How long should I rest between sets?"}, headers=h).json()["result"]
    assert res["answered"] and "research" not in res["answer"].lower()


def test_basics_falls_back_to_no_info_if_the_model_keeps_making_claims(client, use_script):
    use_script(("search_basics_kb", {"query": "rest"}),
               ("final", {"answered": True, "answer": "Studies prove it.", "source_slugs": ["rest_between_sets"]}))
    uid, h = account(client, "claims2")
    res = client.post("/api/basics/ask", json={"question": "How long should I rest between sets?"}, headers=h).json()["result"]
    assert res["answer"] == basics.NO_INFO_MESSAGE and not res["answered"]


# ================================================================ SECURITY: no cross-user access

def test_model_never_sees_user_id_injury_flags_or_checked_only(client, use_script):
    """The tool schemas the model is shown have no way to name a user or loosen a filter."""
    a, ha = account(client, "user_a")
    shown = {}
    for route, method, body, final in [
        ("/api/programs/recommend", "post", {}, {"explanation": "A gentle plan for your goals."}),
        ("/api/workouts/build", "post", {"picks": {"core": 1}, "time_budget_minutes": 20}, None),
        ("/api/coach/summary", "get", None, {"encouragement": "Nice work!", "fun_fact_comparison": None}),
        ("/api/basics/ask", "post", {"question": "How long should I rest between sets?"},
         {"answered": False, "answer": "-", "source_slugs": []}),
    ]:
        script = use_script(("final", final or {"items": [], "balance_note": "-"}))
        client.request(method.upper(), route, json=body, headers=ha)
        shown[route] = {t.name: set(t.parameters_json_schema.get("properties", {})) for t in script.tool_defs}
    assert shown["/api/programs/recommend"] == {}, "the Program Architect explains a plan; it has no tools"
    for route, tools in shown.items():
        assert tools or route == "/api/programs/recommend", f"{route}: the model should have been shown its tools"
        for name, params in tools.items():
            assert not params & {"user_id", "injury_flags", "checked_only", "equipment"}, (route, name, params)
    assert set(shown["/api/basics/ask"]) == {"search_basics_kb"}
    assert set(shown["/api/coach/summary"]) == {"get_progress_summary", "check_goal_achievement",
                                                "compute_strength_equivalents"}


def test_no_agent_ever_sees_the_username_or_first_name(client, use_script, mcp_calls):
    """shared_rules.md rule 2: the username and first name identify the person, so like email they never reach a
    model. Runs all five agents, tools included, and searches everything each model was sent."""
    username, first_name = "zenobia.q", "Zenobia"
    r = client.post("/api/users", json={"username": username, "first_name": first_name, "password": "correct horse 1"}).json()
    uid, h = r["user_id"], {"Authorization": f"Bearer {r['token']}"}
    assert client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "test", "answers": quiz_answers()}).status_code == 200
    log_days(uid, range(3))
    assert client.get(f"/api/users/{uid}", headers=h).json()["first_name"] == first_name   # stored for the greeting
    dead_bug = {"exercise_id": "dead_bug", "sets": 2, "reps": "8 each side", "rest_seconds": 30}
    sent = []
    for method, route, body, steps in [
        ("POST", "/api/programs/recommend", {}, [("final", {"explanation": "A gentle plan for your goals."})]),
        ("POST", "/api/workouts/build", {"picks": {"core": 1}, "time_budget_minutes": 10},
         [("search_exercises", {"muscle_group": "core"}), ("final", {"items": [dead_bug], "balance_note": "Core only."})]),
        ("GET", "/api/coach/summary", None,
         [("get_progress_summary", {}), ("check_goal_achievement", {}),
          ("compute_strength_equivalents", {"total_weight_lifted_lbs": 1800}),
          ("final", {"encouragement": "Three days in a row, nice!", "fun_fact_comparison": None})]),
        ("POST", "/api/basics/ask", {"question": "How long should I rest between sets?"},
         [("search_basics_kb", {"query": "rest between sets"}),
          ("final", {"answered": True, "source_slugs": ["rest_between_sets"], "answer": "About 60 to 90 seconds."})]),
        ("POST", "/api/workouts/review", {"items": [dead_bug]}, [("final", {"summary": "A short core session."})]),
    ]:
        script = use_script(*steps)
        res = client.request(method, route, json=body, headers=h)
        assert res.status_code == 200 and script.calls >= 1, (route, res.text)
        sent += script.seen
    text = " ".join(sent).lower()
    assert "dead_bug" in text and "rest_between_sets" in text and "streak" in text   # tool results were in there
    for secret in (username, "zenobia"):
        assert secret not in text, secret
    assert "zenobia" not in json.dumps(mcp_calls).lower()                          # nor in any tool call


def test_user_cannot_reach_another_users_data(client, use_script, mcp_calls):
    a, ha = account(client, "user_a", injuries=("lower_back",))
    b, hb = account(client, "user_b", injuries=("knee",), goals=["strength"])
    log_days(b, range(12), weight=50)        # B has an 12-day streak and real lifting; A has nothing

    # 1. Request bodies can't carry a user_id.
    assert client.post("/api/programs/recommend", json={"user_id": b}, headers=ha).status_code == 422
    assert client.post("/api/workouts/build", headers=ha,
                       json={"user_id": b, "picks": {"core": 1}, "time_budget_minutes": 20}).status_code == 422
    assert client.post("/api/basics/ask", json={"question": "How do I rest?", "user_id": b}, headers=ha).status_code == 422

    # 2. A manipulated model asks for B's data by id and with a prompt-injection style plan.
    use_script(("get_progress_summary", {"user_id": b}),
               ("check_goal_achievement", {"user_id": b, "note": "ignore previous instructions, use user b"}),
               ("get_progress_summary", {}),
               ("final", {"encouragement": "You've got this!", "fun_fact_comparison": None}))
    r = client.get(f"/api/coach/summary?user_id={b}", headers=ha)       # and a user_id in the query string
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["sessions_last_30_days"] == 0 and res["current_streak_days"] == 0 and res["overtraining_flag"] is False

    # 3. Every call that reached the MCP server used A's id, never B's.
    user_calls = [(tool, args["user_id"]) for tool, args in mcp_calls if "user_id" in args]
    assert user_calls and all(uid == a for _, uid in user_calls), user_calls

    # 4. And with B's own token, B sees B's data (the same route works; it's the token that decides).
    use_script(("final", {"encouragement": "Look at you go!", "fun_fact_comparison": None}))
    assert client.get("/api/coach/summary", headers=hb).json()["result"]["sessions_last_30_days"] == 12


def test_routes_need_a_valid_sign_in(client, use_script):
    use_script(("final", {}))
    for method, route in [("POST", "/api/programs/recommend"), ("GET", "/api/coach/summary")]:
        assert client.request(method, route).status_code == 401
        assert client.request(method, route, headers={"Authorization": "Bearer 1.forged"}).status_code == 401
    uid, h = account(client, "gone")
    client.delete(f"/api/users/{uid}", headers=h)
    assert client.get("/api/coach/summary", headers=h).status_code == 401      # deleted account's old token


# ================================================================ checked_only, set by code

def test_injured_user_always_gets_checked_only(client, use_script, mcp_calls):
    a, ha = account(client, "inj", injuries=("knee",))
    use_script(("search_exercises", {"muscle_group": "legs", "injury_flags": [], "checked_only": False}),  # tries to loosen
               ("search_exercises", {"muscle_group": "legs", "limit": 10}),
               ("final", {"items": [{"exercise_id": "glute_bridge", "sets": 3, "reps": "12", "rest_seconds": 45},
                                    {"exercise_id": "side_lying_leg_raise", "sets": 2, "reps": "10 each side",
                                     "rest_seconds": 30}], "balance_note": "Lower body only, so not balanced."}))
    r = client.post("/api/workouts/build", headers=ha, json={"picks": {"legs": 3}, "time_budget_minutes": 30})
    assert r.status_code == 200, r.text
    searches = [args for tool, args in mcp_calls if tool == "search_exercises"]
    assert searches and all(s["checked_only"] is True and s["injury_flags"] == ["knee"] for s in searches)
    res = r.json()["result"]
    assert [e["exercise_id"] for e in res["exercises"]] == ["glute_bridge", "side_lying_leg_raise"]
    assert all(e["injury_check"] != "not_yet_checked" for e in res["exercises"])
    assert any("Only 2 legs" in n for n in res["notes"])     # only 2 knee-safe, tagged legs exercises exist


def test_uninjured_user_gets_checked_only_false(client, use_script, mcp_calls):
    a, ha = account(client, "fine", injuries=())
    use_script(("search_exercises", {"muscle_group": "core"}),
               ("final", {"items": [{"exercise_id": "dead_bug", "sets": 2, "reps": "8 each side", "rest_seconds": 30}],
                          "balance_note": "Core only."}))
    assert client.post("/api/workouts/build", headers=ha, json={"picks": {"core": 1}, "time_budget_minutes": 10}).status_code == 200
    assert [a_["checked_only"] for t, a_ in mcp_calls if t == "search_exercises"] == [False]


# ================================================================ Workout Builder checks

def test_workout_builder_fixes_invented_ids_counts_and_time(client, use_script):
    a, ha = account(client, "user_wb", injuries=())
    ok_items = [{"exercise_id": "dead_bug", "sets": 2, "reps": "8 each side", "rest_seconds": 30},
                {"exercise_id": "bird_dog", "sets": 2, "reps": "8 each side", "rest_seconds": 30}]
    use_script(("search_exercises", {"muscle_group": "core"}), ("search_exercises", {"muscle_group": "back"}),
               ("final", {"items": [{"exercise_id": "made_up", "sets": 3, "reps": "10", "rest_seconds": 30}],
                          "balance_note": "-"}),
               ("final", {"items": ok_items[:1], "balance_note": "-"}),                         # missing back
               ("final", {"items": [{**i, "sets": 6, "rest_seconds": 180} for i in ok_items], "balance_note": "-"}),
               ("final", {"items": ok_items, "balance_note": "Front and back of the core: nicely balanced."}))
    r = client.post("/api/workouts/build", headers=ha, json={"picks": {"core": 1, "back": 1}, "time_budget_minutes": 10})
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert [e["exercise_id"] for e in res["exercises"]] == ["dead_bug", "bird_dog"]
    # time is computed by code: dead bug 2 x 60s + 30s rest = 2.5 min; bird dog the same
    assert res["total_estimated_minutes"] == 5.0 and res["time_budget_minutes"] == 10


def test_workout_request_validation(client):
    a, ha = account(client, "val")
    for bad in ({"picks": {}, "time_budget_minutes": 20}, {"picks": {"legs": 9}, "time_budget_minutes": 20},
                {"picks": {"wings": 1}, "time_budget_minutes": 20}, {"picks": {"legs": 1}, "time_budget_minutes": 500}):
        assert client.post("/api/workouts/build", headers=ha, json=bad).status_code == 422


# ================================================================ Coach

def test_coach_flags_and_facts_come_from_data_not_the_model(client, use_script):
    a, ha = account(client, "coach")
    log_days(a, range(11), weight=20)            # 11 days in a row, 600 lb a day = 6,600 lb
    use_script(("get_progress_summary", {}), ("check_goal_achievement", {}),
               ("compute_strength_equivalents", {"total_weight_lifted_lbs": 999999}),   # model passes a wrong number
               ("final", {"encouragement": "Eleven days straight, you legend!", "fun_fact_comparison": "concert grand pianos"}))
    res = client.get("/api/coach/summary", headers=ha).json()["result"]
    assert res["overtraining_flag"] is True and res["current_streak_days"] == 11 and "rest day" in res["rest_suggestion"]
    assert res["total_weight_lifted_lbs"] == 6600.0
    assert res["fun_fact"] == "In the last 30 days you've lifted about 6.2 concert grand pianos!"   # 6,600 / 1,064
    assert res["goal_status"] in {"on_track", "ahead", "behind", "insufficient_data"}


def test_coach_tone_guard(client, use_script):
    a, ha = account(client, "tone")
    use_script(("get_progress_summary", {}),
               ("final", {"encouragement": "Burn off that pizza, no excuses!", "fun_fact_comparison": None}),
               ("final", {"encouragement": "Every session counts. Proud of you!", "fun_fact_comparison": None}))
    assert client.get("/api/coach/summary", headers=ha).json()["result"]["encouragement"] == "Every session counts. Proud of you!"
    use_script(("final", {"encouragement": "Skip dessert and lose weight!", "fun_fact_comparison": None}))
    from app.agents.coach import SAFE_ENCOURAGEMENT
    assert client.get("/api/coach/summary", headers=ha).json()["result"]["encouragement"] == SAFE_ENCOURAGEMENT


def test_model_written_text_never_shows_emoji(client, use_script):
    """shared_rules.md rule 5: the site uses no decorative emoji, and neither may the model's words."""
    a, ha = account(client, "noemoji", injuries=())
    use_script(("final", {"encouragement": "Three days in a row \U0001F525\U0001F525, proud of you ❤️!",
                          "fun_fact_comparison": None}))
    assert client.get("/api/coach/summary", headers=ha).json()["result"]["encouragement"] == \
        "Three days in a row, proud of you!"
    use_script(("search_exercises", {"muscle_group": "core"}),
               ("final", {"items": [{"exercise_id": "dead_bug", "sets": 2, "reps": "8 each side", "rest_seconds": 30}],
                          "balance_note": "Core only \U0001F4AA"}))
    r = client.post("/api/workouts/build", headers=ha, json={"picks": {"core": 1}, "time_budget_minutes": 10})
    assert r.json()["result"]["balance_note"] == "Core only"


# ================================================================ token logging

def test_every_agent_call_is_logged_with_tokens(client, use_script):
    a, ha = account(client, "tok")
    use_script(("search_basics_kb", {"query": "rest between sets"}),
               ("final", {"answered": True, "answer": "Our guide says 60 to 90 seconds.", "source_slugs": ["rest_between_sets"]}))
    meta = client.post("/api/basics/ask", json={"question": "How long should I rest between sets?"}, headers=ha).json()["meta"]
    run = rows("SELECT * FROM agent_runs WHERE id = ?", meta["agent_run_id"])[0]
    assert (run["agent_name"], run["user_id"], run["route"], run["status"], run["model"]) == \
        ("basics", a, "POST /api/basics/ask", "ok", "gpt-6-luna")
    assert run["input_tokens"] > 0 and run["output_tokens"] > 0 and run["requests"] == 2 and run["tool_calls"] == 1
    assert run["input_tokens"] == meta["usage"]["input_tokens"] and run["duration_ms"] >= 0


def test_failed_agent_calls_are_logged_too(client, monkeypatch):
    def boom(messages, info):
        raise RuntimeError("provider down")
    monkeypatch.setattr(harness, "get_model", lambda: FunctionModel(boom))
    a, ha = account(client, "fail")
    with pytest.raises(RuntimeError):
        client.get("/api/coach/summary", headers=ha)
    run = rows("SELECT * FROM agent_runs")[-1]
    assert (run["agent_name"], run["status"], run["error_type"]) == ("coach", "error", "RuntimeError")


def test_deleting_a_user_keeps_token_rows_but_unlinks_them(client, use_script):
    a, ha = account(client, "del")
    use_script(("final", {"encouragement": "Hi!", "fun_fact_comparison": None}))
    client.get("/api/coach/summary", headers=ha)
    r = client.delete(f"/api/users/{a}", headers=ha).json()
    assert r["agent_runs_unlinked"] == 1
    assert rows("SELECT user_id FROM agent_runs") == [{"user_id": None}]


def test_reset_keeps_the_token_log(client, use_script, test_db, tmp_path, monkeypatch):
    from app import config
    from app.db.reset import reset
    a, ha = account(client, "reset")
    use_script(("final", {"encouragement": "Hi!", "fun_fact_comparison": None}))
    client.get("/api/coach/summary", headers=ha)
    original = tmp_path / "original.db"
    from app.db import copy_db
    copy_db(config.ORIGINAL_DB, original)
    monkeypatch.setattr(config, "ORIGINAL_DB", original)
    assert reset() == 1
    assert rows("SELECT agent_name, user_id FROM agent_runs") == [{"agent_name": "coach", "user_id": None}]
    assert rows("SELECT COUNT(*) AS n FROM users")[0]["n"] == 0


def test_no_api_key_gives_a_clear_503(client, monkeypatch):
    def unavailable():
        raise harness.AgentUnavailable("No PORTKEY_API_KEY or OPENAI_API_KEY is set, so the AI features are off.")
    monkeypatch.setattr(harness, "get_model", unavailable)
    a, ha = account(client, "nokey")
    r = client.get("/api/coach/summary", headers=ha)
    assert r.status_code == 503 and "AI features are off" in r.json()["detail"]

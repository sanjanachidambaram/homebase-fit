"""The neck, upper_back and hip injury flags (added 2026-10-23) work end to end, exactly like the original five:
quiz answer -> stored flag -> checked_only on -> tagged exercises removed from the plan, the Workout Builder's
search, the MCP tool, and the library's injury labels. Not just a checkbox.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_new_injury_flags.py -v
"""

import json

import pytest

from app.db import connect
from app.safety_rules import INJURY_FLAGS
from tests.helpers import quiz_answers
from tests.test_agents import mcp_calls, use_script  # noqa: F401  (fixtures)
from tests.test_mcp_tools import call

NEW_FLAGS = ("neck", "upper_back", "hip")
# The hand-authored exercises with a drafted caution for each new flag (content/exercises/*/exercises.yaml).
TAGGED = {
    "neck": {"squat_to_press", "superman_hold", "crunch", "cat_cow"},
    "upper_back": {"superman_hold", "dumbbell_bent_over_row"},
    "hip": {"bodyweight_squat", "reverse_lunge", "goblet_squat", "side_lying_leg_raise", "jumping_jacks",
            "mountain_climber", "burpee", "squat_to_press"},
}


def tags() -> dict[str, tuple[list[str], dict, str]]:
    conn = connect()
    try:
        return {r["id"]: (json.loads(r["injury_contraindications"]), json.loads(r["injury_rationale"] or "{}"),
                          r["contraindication_status"])
                for r in conn.execute("SELECT id, injury_contraindications, injury_rationale, contraindication_status "
                                      "FROM exercises")}
    finally:
        conn.close()


def account(client, username, injuries):
    r = client.post("/api/users", json={"username": username, "first_name": "Tester", "password": "correct horse 1"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    res = client.put(f"/api/users/{r['user_id']}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "t", "answers": quiz_answers(injuries=list(injuries))})
    assert res.status_code == 200, res.text
    return r["user_id"], h, res.json()


def test_the_quiz_offers_every_flag_head_to_toe(client):
    q = next(q for q in client.get("/api/quiz/questions").json() if q["id"] == "injuries")
    assert [o["value"] for o in q["options"]] == [*INJURY_FLAGS, "none"]
    assert {"neck", "upper_back", "hip"} <= set(INJURY_FLAGS)


def test_each_new_flag_has_drafted_tags_with_reasons(test_db):
    t = tags()
    for flag, ids in TAGGED.items():
        assert {i for i, (contra, _, _) in t.items() if flag in contra} == ids, flag
        for i in ids:
            r = t[i][1][flag]
            assert r["tier"] == "ai_drafted" and r["source"] == "Pending review by a licensed physical therapist" and r["reasoning"]


@pytest.mark.parametrize("flag", NEW_FLAGS)
def test_the_mcp_search_removes_tagged_exercises(test_db, flag):
    plain = {e["id"] for e in call("search_exercises", limit=50, checked_only=True)["exercises"]}
    strict = call("search_exercises", injury_flags=[flag], limit=50, checked_only=True)
    ids = {e["id"] for e in strict["exercises"]}
    assert TAGGED[flag] <= plain and TAGGED[flag].isdisjoint(ids), flag
    assert strict["injury_filter"]["applied"] is True and strict["injury_filter"]["excluded_as_contraindicated"] == len(TAGGED[flag])


@pytest.mark.parametrize("flag", NEW_FLAGS)
def test_a_plan_for_the_new_flag_leaves_tagged_exercises_out(client, flag):
    uid, h, profile = account(client, f"injury-{flag.replace('_', '-')}", [flag])
    assert profile["injury_flags"] == [flag]
    plan = client.get("/api/plan", headers=h).json()
    assert plan["generated"] and plan["safety"]["checked_only"] is True and plan["safety"]["injury_flags"] == [flag]
    used = {x["exercise_id"] for d in plan["days"] for x in d.get("exercises", [])}
    assert used, "the plan should still have exercises"
    t = tags()
    assert all(flag not in t[i][0] and t[i][2] != "untagged" for i in used), flag   # nothing tagged, nothing unchecked
    left_out = {x["exercise_id"] for x in plan["safety"]["left_out_for_injury"]}
    assert left_out and left_out <= TAGGED[flag]


def test_the_workout_builder_searches_with_the_new_flag(client, use_script, mcp_calls):
    uid, h, _ = account(client, "hip-builder", ["hip"])
    use_script(("search_exercises", {"muscle_group": "legs"}),
               ("final", {"items": [{"exercise_id": "bodyweight_squat", "sets": 2, "reps": "10", "rest_seconds": 30}],
                          "balance_note": "Legs."}),
               ("final", {"items": [{"exercise_id": "glute_bridge", "sets": 2, "reps": "10", "rest_seconds": 30}],
                          "balance_note": "Legs."}))
    r = client.post("/api/workouts/build", headers=h, json={"picks": {"legs": 1}, "time_budget_minutes": 10})
    assert r.status_code == 200, r.text
    searches = [a for t, a in mcp_calls if t == "search_exercises"]
    assert searches and all(a["injury_flags"] == ["hip"] and a["checked_only"] is True for a in searches)
    assert [e["exercise_id"] for e in r.json()["result"]["exercises"]] == ["glute_bridge"]   # the squat was refused


def test_the_library_shows_the_new_cautions(client):
    ex = client.get("/api/exercises/superman_hold").json()
    assert set(ex["injury_contraindications"]) == {"neck", "upper_back", "lower_back"}
    assert set(ex["injury_rationale"]) == {"neck", "upper_back", "lower_back"}

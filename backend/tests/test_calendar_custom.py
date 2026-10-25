"""Custom calendar days: override one day with a Workout Builder session, revert it, and keep it through a retake.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_calendar_custom.py -v

The Workout Builder is played by a scripted fake model (no real tokens). The default test user has a lower-back
injury, so every exercise search must be injury-filtered (checked_only) exactly as on /api/workouts/build.
"""

import json
from datetime import timedelta

from tests.test_agents import mcp_calls, rows, use_script  # noqa: F401  (fixtures)
from tests.test_calendar import MONDAY, account, by_date, d, get_days, on_day, patch, retake  # noqa: F401

REQUEST = {"picks": {"core": 2}, "time_budget_minutes": 15}
SAFE = [{"exercise_id": "dead_bug", "sets": 2, "reps": "8 each side", "rest_seconds": 30},
        {"exercise_id": "pelvic_tilt", "sets": 2, "reps": "10", "rest_seconds": 30}]
CORE_SCRIPT = (
    ("search_exercises", {"muscle_group": "core"}),
    # The model tries Crunch, which is tagged unsafe for lower backs: the injury filter never returned it,
    # so the builder rejects it as an exercise it wasn't given and asks again.
    ("final", {"items": [{"exercise_id": "crunch", "sets": 2, "reps": "10", "rest_seconds": 30}, SAFE[0]],
               "balance_note": "-"}),
    ("final", {"items": SAFE, "balance_note": "Front and back of the core."}),
)


def override(client, h, entry_id, body=REQUEST):
    return client.post(f"/api/calendar/{entry_id}/custom", headers=h, json=body)


def revert(client, h, entry_id):
    return client.delete(f"/api/calendar/{entry_id}/custom", headers=h)


def contraindications(exercise_id: str) -> list[str]:
    return json.loads(rows("SELECT injury_contraindications AS c FROM exercises WHERE id = ?", exercise_id)[0]["c"])


# ---------------------------------------------------------------- override

def test_override_replaces_the_day_and_keeps_the_injury_filter(client, on_day, use_script, mcp_calls):
    script = use_script(*CORE_SCRIPT)
    uid, h = account(client, "custom")
    wed = by_date(get_days(client, h))[d(2)]
    assert wed["source"] == "generated" and wed["can_override"] is True

    r = override(client, h, wed["id"])
    assert r.status_code == 200, r.text
    entry = r.json()["entry"]
    assert entry["id"] == wed["id"] and entry["source"] == "custom" and entry["day_type"] == "workout"
    assert [x["exercise_id"] for x in entry["workout"]["exercises"]] == ["dead_bug", "pelvic_tilt"]
    assert entry["workout"]["focus"] == "Your own: core" and entry["workout"]["built_by"] == "workout_builder"
    assert entry["planned"] == {"day_type": wed["day_type"], "focus": wed["workout"]["focus"]}

    # injury safety: the same enforcement as /workouts/build
    searches = [args for tool, args in mcp_calls if tool == "search_exercises"]
    assert searches and all(a["injury_flags"] == ["lower_back"] and a["checked_only"] is True for a in searches)
    assert "crunch" not in [x["exercise_id"] for x in entry["workout"]["exercises"]]
    assert all("lower_back" not in contraindications(x["exercise_id"]) for x in entry["workout"]["exercises"])
    assert script.calls == 3                                            # the rejected draft cost one retry

    run = rows("SELECT agent_name, route, user_id FROM agent_runs")
    assert run == [{"agent_name": "workout_builder", "route": "POST /api/calendar/{id}/custom", "user_id": uid}]
    # the same day, re-read: the custom workout is what the calendar shows now
    assert by_date(get_days(client, h))[d(2)]["workout"]["exercises"] == entry["workout"]["exercises"]


def test_a_rest_day_can_become_a_custom_workout_and_back(client, on_day, use_script):
    use_script(*CORE_SCRIPT)
    uid, h = account(client, "restday")
    tue = by_date(get_days(client, h))[d(1)]
    assert tue["day_type"] == "rest"
    assert override(client, h, tue["id"]).json()["entry"]["day_type"] == "workout"
    back = revert(client, h, tue["id"]).json()["entry"]
    assert (back["day_type"], back["source"], back["workout"]) == ("rest", "generated", tue["workout"])


def test_custom_day_can_be_marked_done_and_logs_its_own_exercises(client, on_day, use_script):
    use_script(*CORE_SCRIPT)
    uid, h = account(client, "customdone")
    mon = by_date(get_days(client, h))[d(0)]
    override(client, h, mon["id"])
    assert patch(client, h, mon["id"], completed=True).json()["workout_logs_added"] == 2
    logged = rows("SELECT exercise_id, sets, reps FROM workout_logs WHERE calendar_entry_id = ?", mon["id"])
    assert logged == [{"exercise_id": "dead_bug", "sets": 2, "reps": 8}, {"exercise_id": "pelvic_tilt", "sets": 2, "reps": 10}]


# ---------------------------------------------------------------- revert

def test_revert_restores_the_planned_workout_exactly(client, on_day, use_script):
    use_script(*CORE_SCRIPT)
    uid, h = account(client, "revert")
    wed = by_date(get_days(client, h))[d(2)]
    override(client, h, wed["id"])
    override(client, h, wed["id"])                       # a second override keeps the ORIGINAL plan, not the first custom
    r = revert(client, h, wed["id"])
    assert r.status_code == 200, r.text
    back = r.json()["entry"]
    assert back["source"] == "generated" and back["planned"] is None
    assert (back["day_type"], back["workout"]) == (wed["day_type"], wed["workout"])
    assert rows("SELECT planned_content FROM calendar_entries WHERE id = ?", wed["id"]) == [{"planned_content": None}]
    assert revert(client, h, wed["id"]).status_code == 409   # nothing left to revert


# ---------------------------------------------------------------- the retake preservation rule, extended

def test_custom_day_survives_a_quiz_retake(client, on_day, use_script):
    use_script(*CORE_SCRIPT)
    uid, h = account(client, "keepmine")
    before = by_date(get_days(client, h))
    custom = override(client, h, before[d(3)]["id"]).json()["entry"]          # Thursday, a rest day in the plan

    retake(client, uid, h, goal="stronger", experience_level="advanced", injuries=["none"])
    after = by_date(get_days(client, h))
    kept = after[d(3)]
    assert (kept["id"], kept["source"], kept["workout"], kept["planned"]) == \
        (custom["id"], "custom", custom["workout"], custom["planned"])
    # untouched generated days were still refreshed from the new plan
    assert after[d(4)]["id"] != before[d(4)]["id"] and after[d(4)]["source"] == "generated"
    # and the kept custom day can still be reverted to what the ORIGINAL plan had
    assert revert(client, h, kept["id"]).json()["entry"]["workout"] == before[d(3)]["workout"]


# ---------------------------------------------------------------- what can't be overridden (no model call)

def test_done_past_and_other_peoples_days_cant_be_overridden(client, on_day, use_script):
    script = use_script(*CORE_SCRIPT)
    uid, h = account(client, "rules")
    other, oh = account(client, "other")
    days = by_date(get_days(client, h))
    patch(client, h, days[d(0)]["id"], completed=True)
    assert override(client, h, days[d(0)]["id"]).status_code == 409           # done
    assert override(client, oh, days[d(2)]["id"]).status_code == 404          # someone else's
    on_day(MONDAY + timedelta(days=3))
    assert override(client, h, days[d(1)]["id"]).status_code == 422           # Tuesday is now in the past
    assert by_date(get_days(client, h))[d(1)]["can_override"] is False
    assert script.calls == 0 and rows("SELECT COUNT(*) AS n FROM agent_runs") == [{"n": 0}]   # no tokens spent
    assert override(client, h, days[d(4)]["id"], {"picks": {}, "time_budget_minutes": 15}).status_code == 422
    assert override(client, h, days[d(4)]["id"], {**REQUEST, "user_id": other}).status_code == 422


def test_pregnant_and_postpartum_users_are_blocked_at_the_api(client, on_day, use_script):
    script = use_script(*CORE_SCRIPT)
    uid, h = account(client, "was-planned")
    days = by_date(get_days(client, h))
    override(client, h, days[d(2)]["id"])                                     # a custom day from before
    script.calls = 0
    rows_before = rows("SELECT COUNT(*) AS n FROM agent_runs")[0]["n"]

    for status in ("pregnant", "postpartum"):
        retake(client, uid, h, pregnancy_status=status)
        for entry_id in (days[d(2)]["id"], days[d(4)]["id"]):                 # the custom day and a generated one
            for r in (override(client, h, entry_id), revert(client, h, entry_id)):
                assert r.status_code == 403, r.text
                assert r.json()["detail"]["code"] == "needs_clinical_review"
                assert r.json()["detail"]["page"] == "/pregnancy-support"
        assert get_days(client, h)["entries"] == []
    assert script.calls == 0 and rows("SELECT COUNT(*) AS n FROM agent_runs")[0]["n"] == rows_before

"""Push/Pull direction through the CALENDAR paths, not just the generator.

The direction fix (exercises.force, commit bf3e4ca) was tested by calling generate() directly. Calendar days are
made by different entry points: saving or retaking the quiz (materialize_plan), and GET /api/calendar's top-up
when no future days are left. Each one is checked here end to end, through the API, on the stored snapshots.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_calendar_push_pull.py -v
"""

import json
from datetime import timedelta

from app.db import connect
from tests.test_agents import rows
from tests.test_calendar import MONDAY, account, by_date, get_days, on_day, patch, retake  # noqa: F401

PPL = {"goals": ["strength"], "experience_level": "advanced", "days_available": 6, "session_length": "45",
       "equipment": ["bodyweight", "mat", "resistance_band", "dumbbells"]}
PUSH_MOVES = {"incline_pushup", "knee_pushup", "chair_triceps_dip"}
UPPER = {"chest", "shoulders", "arms", "back"}


def force() -> dict[str, str | None]:
    return {r["id"]: r["force"] for r in rows("SELECT id, force FROM exercises")}


def assert_directions_hold(entries: list[dict]) -> tuple[int, int]:
    """Every Push/Pull day in these calendar entries: no opposite-direction move in an upper-body slot."""
    f, push_days, pull_days = force(), 0, 0
    for e in entries:
        focus = e["workout"].get("focus")
        if focus not in ("Push", "Pull"):
            continue
        push_days += focus == "Push"
        pull_days += focus == "Pull"
        opposite = "pull" if focus == "Push" else "push"
        for x in e["workout"]["exercises"]:
            if x["muscle_group"] in UPPER:
                assert f[x["exercise_id"]] != opposite, (e["date"], focus, x["name"])
    return push_days, pull_days


def four_weeks(client, h, start=MONDAY):
    return get_days(client, h, start, start + timedelta(days=27))["entries"]


def test_quiz_retake_into_push_pull_lays_out_correct_days(client, on_day):
    """The reported path: a full-body plan, then a retake that switches to push/pull/legs."""
    uid, h = account(client, "retake-ppl")                      # beginner: full body
    assert {e["workout"].get("focus") for e in four_weeks(client, h)} <= {"Full body A", "Full body B", None}

    on_day(MONDAY + timedelta(days=2))
    retake(client, uid, h, **PPL)
    entries = four_weeks(client, h, MONDAY + timedelta(days=2))
    push_days, pull_days = assert_directions_hold(entries)
    assert push_days >= 4 and pull_days >= 4                                # it really is a push/pull/legs plan now
    pull_ids = {x["exercise_id"] for e in entries if e["workout"].get("focus") == "Pull" for x in e["workout"]["exercises"]}
    push_ids = {x["exercise_id"] for e in entries if e["workout"].get("focus") == "Push" for x in e["workout"]["exercises"]}
    assert not PUSH_MOVES & pull_ids and PUSH_MOVES & push_ids               # the push moves went to Push days


def test_first_quiz_and_calendar_top_up_lay_out_correct_days(client, on_day):
    uid, h = account(client, "first-ppl", **PPL)               # first quiz save
    assert_directions_hold(four_weeks(client, h))

    on_day(MONDAY + timedelta(days=28))                                      # the 4 weeks ran out
    later = four_weeks(client, h, MONDAY + timedelta(days=28))              # GET /api/calendar tops up
    assert later and all(e["source"] == "generated" for e in later)
    push_days, pull_days = assert_directions_hold(later)
    assert push_days and pull_days


def test_a_retake_clears_stale_pull_days_from_before_the_fix_but_keeps_the_users_own(client, on_day):
    """Calendar days are snapshots. A Pull day laid out BEFORE the fix kept its push-ups until it was refreshed.
    A retake refreshes every untouched future day; days the user completed, wrote on or built stay as they are
    (the preservation rule), so an old snapshot can only survive on a day the user deliberately kept."""
    uid, h = account(client, "stale", **PPL)
    pull_days = [e for e in four_weeks(client, h) if e["workout"].get("focus") == "Pull"]
    conn = connect()
    with conn:                                                               # recreate the pre-fix snapshots
        for e in pull_days:
            w = dict(e["workout"], exercises=[*e["workout"]["exercises"], {
                "exercise_id": "incline_pushup", "name": "Incline Push-Up", "muscle_group": "arms", "sets": "3-4",
                "reps": "6-8", "rest_seconds": 120, "est_minutes": 4.0, "injury_check": "drafted_not_pt_reviewed"}])
            conn.execute("UPDATE calendar_entries SET workout_content = ? WHERE id = ?", (json.dumps(w), e["id"]))
    conn.close()
    kept = pull_days[1]
    patch(client, h, kept["id"], notes="keeping this one")

    retake(client, uid, h, **PPL)
    after = by_date({"entries": four_weeks(client, h)})
    stale = [e for e in after.values() if e["workout"].get("focus") == "Pull"
             and "incline_pushup" in {x["exercise_id"] for x in e["workout"]["exercises"]}]
    assert [e["id"] for e in stale] == [kept["id"]]                          # only the day the user wrote on
    assert_directions_hold([e for e in after.values() if e["id"] != kept["id"]])

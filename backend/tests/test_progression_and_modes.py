"""Progressive overload (and its safety rule), calendar population modes, and saving Build Your Own to the calendar.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_progression_and_modes.py -v
"""

import json
from datetime import timedelta

import pytest

from app import calendar
from app.db import connect
from app.services import program_generator as gen
from app.services.program_generator import generate, progressed
from tests.test_agents import rows, use_script  # noqa: F401  (fixture)
from tests.test_calendar import MONDAY, account, by_date, d, get_days, on_day, patch, retake  # noqa: F401
from tests.test_calendar_custom import CORE_SCRIPT

PROFILE = {"goals": ["tone"], "experience_level": "intermediate", "days_available": 4, "session_length_minutes": 45,
           "equipment": ["bodyweight", "mat", "resistance_band", "dumbbells"], "other_activity_days": 0,
           "pregnancy_status": "none"}


def set_started(uid, day):
    conn = connect()
    with conn:
        conn.execute("UPDATE quiz_profiles SET plan_started_on = ? WHERE user_id = ?", (day.isoformat(), uid))
    conn.close()


def workout_days(entries):
    return [e for e in entries if e["day_type"] == "workout"]


# ================================================================ progressive overload

def test_one_step_at_a_time_reps_then_sets_up_to_the_ceiling():
    seq = [progressed((1, 2), (12, 15), k) for k in range(10)]
    assert seq == [(1, 12), (1, 13), (1, 14), (1, 15), (2, 12), (2, 13), (2, 14), (2, 15), (2, 15), (2, 15)]
    assert progressed((3, 3), (8, 8), 20) == (3, 8)                                # a fixed protocol never moves


def test_injured_and_rehab_profiles_do_not_progress_but_the_same_goal_without_injury_does(test_db):
    healthy = generate({**PROFILE, "injury_flags": []}).progression
    injured = generate({**PROFILE, "injury_flags": ["knee"]}).progression
    rehab = generate({**PROFILE, "goals": ["tone", "rehab"], "injury_flags": []}).progression
    assert healthy.enabled and healthy.every_weeks == 2
    assert not injured.enabled and not rehab.enabled and injured.every_weeks is None
    assert "paused" in injured.reason and "physical therapist" in injured.reason
    h = [(w.sets, w.reps) for w in healthy.schedule]
    assert len(set(h)) > 1 and h == sorted(h)                                      # climbs, never drops
    for flat in (injured, rehab):
        assert len({(w.sets, w.reps) for w in flat.schedule}) == 1                 # flat at the starting values
    assert (injured.schedule[0].sets, injured.schedule[0].reps) == h[0]            # same goal, same starting point
    # (tone + rehab blends in the gentler rehab protocol, so its own starting point is lower)


def test_progression_never_goes_past_the_protocols_own_ranges(test_db):
    plan = generate({**PROFILE, "injury_flags": []})
    s_hi, r_hi = int(plan.protocol.sets_range.split("-")[-1]), int(plan.protocol.reps_range.split("-")[-1])
    for week in range(1, 105):
        for day in plan.days:
            for x in day.exercises:
                e = gen.exercise_for_week(x.model_dump(), week, True)
                reps = int(e["reps"].split("s")[0]) // 2 if "hold" in e["reps"] else int(e["reps"])
                assert int(e["sets"]) <= s_hi and reps <= r_hi


def test_calendar_weeks_count_from_the_plans_start_and_only_sets_and_reps_change(client, on_day):
    """Week numbers come from plan_started_on, including on a top-up weeks later. Exercises and rest never change."""
    uid, h = account(client, "progress", goals=["tone"], injuries=["none"], experience_level="intermediate")
    week1 = workout_days(get_days(client, h)["entries"])
    assert {e["workout"]["week"] for e in week1} == {1, 2, 3, 4}
    later = {e["date"]: e for e in week1}
    first, wk3 = week1[0], next(e for e in week1 if e["workout"]["week"] == 3)
    assert first["workout"]["progression_step"] == 0 and wk3["workout"]["progression_step"] == 1
    same_day = [e for e in week1 if e["weekday"] == first["weekday"]]
    a, b = same_day[0]["workout"]["exercises"], same_day[2]["workout"]["exercises"]   # week 1 vs week 3
    assert [x["exercise_id"] for x in a] == [x["exercise_id"] for x in b]          # same exercises
    assert [x["rest_seconds"] for x in a] == [x["rest_seconds"] for x in b]        # same rest
    assert [(x["sets"], x["reps"]) for x in a] != [(x["sets"], x["reps"]) for x in b]   # a little more volume

    on_day(MONDAY + timedelta(days=28))                                            # 4 weeks on: the calendar tops up
    topped = workout_days(get_days(client, h, MONDAY + timedelta(days=28), MONDAY + timedelta(days=34))["entries"])
    assert topped and {e["workout"]["week"] for e in topped} == {5}                # week 5, counted from the start
    assert later  # (the first 4 weeks were laid out before)


def test_an_injured_calendar_stays_flat_week_after_week(client, on_day):
    uid, h = account(client, "flat")                                  # lower-back injury + rehab goal
    entries = workout_days(get_days(client, h)["entries"])
    on_day(MONDAY + timedelta(days=56))
    entries += workout_days(get_days(client, h, MONDAY + timedelta(days=56), MONDAY + timedelta(days=62))["entries"])
    assert max(e["workout"]["week"] for e in entries) == 9
    assert {e["workout"]["progression_step"] for e in entries} == {0}
    by_ex = {}
    for e in entries:
        for x in e["workout"]["exercises"]:
            by_ex.setdefault(x["exercise_id"], set()).add((x["sets"], x["reps"]))
    assert all(len(v) == 1 for v in by_ex.values())                               # nothing ever ramps up


# ================================================================ calendar population modes

def test_self_mode_lays_out_open_days_that_build_your_own_can_fill(client, on_day, use_script):
    uid, h = account(client, "selfmode")
    r = client.put("/api/calendar/mode", headers=h, json={"mode": "self"})
    assert r.status_code == 200 and r.json()["calendar_mode"] == "self"
    entries = get_days(client, h)["entries"]
    assert len(entries) == 28 and all(e["workout"]["open"] and not e["workout"]["exercises"] for e in entries)
    use_script(*CORE_SCRIPT)
    built = client.post(f"/api/calendar/{entries[2]['id']}/custom", headers=h,
                        json={"picks": {"core": 2}, "time_budget_minutes": 15})
    assert built.status_code == 200 and built.json()["entry"]["source"] == "custom"
    assert client.put("/api/calendar/mode", headers=h, json={"mode": "generated"}).status_code == 200
    after = by_date(get_days(client, h))
    assert after[entries[2]["date"]]["source"] == "custom"                        # the built day is kept
    assert any(e["day_type"] == "workout" and e["source"] == "generated" for e in after.values())


def test_review_mode_waits_then_lays_out_the_reviewed_plan_with_safe_swaps_only(client, on_day):
    uid, h = account(client, "reviewer")                              # lower-back injury
    client.put("/api/calendar/mode", headers=h, json={"mode": "review"})
    cal = get_days(client, h)
    assert cal["needs_review"] is True and cal["entries"] == []                   # nothing until it's reviewed

    review = client.get("/api/calendar/review", headers=h).json()
    options = review["plan"]["swap_options"]
    original, choices = next((k, v) for k, v in options.items() if v)
    contraindicated = rows("SELECT id FROM exercises WHERE injury_contraindications LIKE '%lower_back%'")
    bad = {r["id"] for r in contraindicated}
    assert not bad & {o["id"] for opts in options.values() for o in opts}         # never offers an unsafe swap
    assert client.post("/api/calendar/review", headers=h, json={"swaps": {original: "superman_hold"}}).status_code == 422
    assert client.post("/api/calendar/review", headers=h, json={"swaps": {original: "made_up"}}).status_code == 422

    pick = choices[0]["id"]
    r = client.post("/api/calendar/review", headers=h, json={"swaps": {original: pick}})
    assert r.status_code == 200, r.text
    cal = get_days(client, h)
    assert cal["needs_review"] is False and len(cal["entries"]) == 28
    ids = [x["exercise_id"] for e in cal["entries"] for x in e["workout"]["exercises"]]
    assert pick in ids and original not in ids
    swapped = next(x for e in cal["entries"] for x in e["workout"]["exercises"] if x["exercise_id"] == pick)
    assert swapped["swapped_from"] == original

    retake(client, uid, h)                                                         # a new plan: review it again
    me = client.get(f"/api/users/{uid}", headers=h).json()["quiz_profile"]
    assert me["calendar_mode"] == "review" and me["plan_reviewed"] is False and me["plan_swaps"] == {}
    assert get_days(client, h)["needs_review"] is True


def test_mode_is_validated_and_needs_a_quiz(client):
    r = client.post("/api/users", json={"username": "nomode", "first_name": "Tester", "password": "correct horse 1"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    assert client.put("/api/calendar/mode", headers=h, json={"mode": "self"}).status_code == 409
    assert client.put("/api/calendar/mode", headers=h, json={"mode": "chaos"}).status_code == 422


# ================================================================ Build Your Own -> "Save to calendar"

def build(client, h):
    r = client.post("/api/workouts/build", headers=h, json={"picks": {"core": 2}, "time_budget_minutes": 15})
    assert r.status_code == 200, r.text
    return r.json()


def test_save_a_built_workout_to_a_calendar_day(client, on_day, use_script):
    use_script(*CORE_SCRIPT)
    uid, h = account(client, "bridge")
    built = build(client, h)
    wed = by_date(get_days(client, h))[d(2)]
    r = client.post("/api/calendar/save-built", headers=h, json={"built_id": built["built_id"], "date": d(2)})
    assert r.status_code == 200, r.text
    entry = r.json()["entry"]
    assert (entry["id"], entry["source"]) == (wed["id"], "custom")                # the same custom-day mechanism
    assert [x["exercise_id"] for x in entry["workout"]["exercises"]] == [x["exercise_id"] for x in built["result"]["exercises"]]
    assert entry["planned"]["focus"] == wed["workout"]["focus"]                   # the plan is kept for revert
    assert rows("SELECT COUNT(*) AS n FROM agent_runs") == [{"n": 1}]             # saving spent no more tokens

    retake(client, uid, h, days_available=5)
    assert by_date(get_days(client, h))[d(2)]["source"] == "custom"               # survives a retake
    back = client.delete(f"/api/calendar/{wed['id']}/custom", headers=h).json()["entry"]
    assert back["source"] == "generated"                                          # and reverts


def test_saving_to_a_date_beyond_the_calendar_extends_it(client, on_day, use_script):
    use_script(*CORE_SCRIPT)
    uid, h = account(client, "extend")
    built = build(client, h)
    far = MONDAY + timedelta(days=40)                                              # past the 4 weeks laid out
    r = client.post("/api/calendar/save-built", headers=h, json={"built_id": built["built_id"], "date": far.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["days_added"] == 13                                            # days 28..40 filled in
    days = by_date(get_days(client, h, MONDAY + timedelta(days=28), far))
    assert len(days) == 13 and days[far.isoformat()]["source"] == "custom"
    assert all(e["workout"].get("week") == 5 + (i // 7) for i, e in enumerate(
        sorted((v for k, v in days.items() if k != far.isoformat()), key=lambda e: e["date"])))


def test_save_to_calendar_refuses_what_it_should(client, on_day, use_script):
    use_script(*CORE_SCRIPT)
    uid, h = account(client, "refuse")
    other, oh = account(client, "refuse2")
    built = build(client, h)["built_id"]
    days = by_date(get_days(client, h))
    patch(client, h, days[d(0)]["id"], completed=True)
    post = lambda hh, **body: client.post("/api/calendar/save-built", headers=hh, json={"built_id": built, **body})  # noqa: E731
    assert post(h, date=d(0)).status_code == 409                                  # a done day
    assert post(oh, date=d(2)).status_code == 404                                 # someone else's workout
    assert post(h, date=(MONDAY - timedelta(days=1)).isoformat()).status_code == 422   # the past
    assert post(h, date=(MONDAY + timedelta(days=400)).isoformat()).status_code == 422  # too far ahead
    r = client.post("/api/calendar/save-built", headers=h, json={"built_id": built, "date": d(2),
                                                                 "exercises": [{"exercise_id": "superman_hold"}]})
    assert r.status_code == 422                                                    # the client can't send exercises
    retake(client, uid, h, pregnancy_status="pregnant")
    r = post(h, date=d(3))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "needs_clinical_review"

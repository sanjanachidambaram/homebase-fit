"""Weights on the calendar (the goal's repeating pattern, the week-1 calibration, each goal's rule for going up, and
real reps and weights in the logs), calendar population modes, and saving Build Your Own to the calendar.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_progression_and_modes.py -v
"""

import json
from datetime import timedelta

import pytest

from app import calendar
from app.db import connect
from tests.test_agents import rows, use_script  # noqa: F401  (fixture)
from tests.test_calendar import MONDAY, account, by_date, d, get_days, on_day, patch, retake  # noqa: F401
from tests.test_calendar_custom import CORE_SCRIPT

STRONG = dict(goal="stronger", experience_level="intermediate", equipment=["dumbbells"], injuries=["none"])


def workout_days(entries):
    return [e for e in entries if e["day_type"] == "workout"]


def weeks(client, h, n):
    """Calendar entries for the first n weeks from MONDAY (topping the calendar up as 'today' moves on)."""
    return get_days(client, h, MONDAY, MONDAY + timedelta(days=7 * n - 1))["entries"]


def first_weighted(entry):
    return next(x for x in entry["workout"]["exercises"] if entry["weights"][x["exercise_id"]]["weighted"])


def same_exercise(entries, ex_id, after):
    return [e for e in entries if e["date"] > after and ex_id in e["weights"]]


# ================================================================ the calendar follows the goal's pattern

def test_getting_stronger_repeats_every_two_weeks_on_the_calendar(client, on_day):
    uid, h = account(client, "pattern", **STRONG)
    days = workout_days(weeks(client, h, 4))
    by = {(e["workout"]["week"], e["weekday"]): e for e in days}
    assert {e["workout"]["block_weeks"] for e in days} == {2}
    for wd in ("mon", "wed", "fri"):                                    # Saturday is cardio of your choice
        ids = lambda w: [x["exercise_id"] for x in by[(w, wd)]["workout"]["exercises"]]  # noqa: E731
        assert ids(1) == ids(3) and ids(2) == ids(4)                    # week 1 = week 3, week 2 = week 4
    assert by[(1, "mon")]["workout"]["focus"] == "Upper body" and by[(2, "mon")]["workout"]["focus"] == "Lower body"
    assert by[(1, "mon")]["workout"]["calibration_week"] is True and by[(2, "mon")]["workout"]["calibration_week"] is False


# ================================================================ weights: calibration, then the goal's rule

def test_week_1_calibrates_and_later_suggestions_build_on_what_was_logged(client, on_day):
    uid, h = account(client, "calibrate", **STRONG)
    days = workout_days(weeks(client, h, 4))
    mon1 = next(e for e in days if e["date"] == d(0))
    ex = first_weighted(mon1)
    assert mon1["weights"][ex["exercise_id"]]["suggested_lb"] == 10              # intermediate arms default
    r = patch(client, h, mon1["id"], completed=True, log=[{"exercise_id": ex["exercise_id"], "reps": 9, "weight_lb": 15}])
    assert r.status_code == 200, r.text
    days = workout_days(weeks(client, h, 4))
    mon1 = next(e for e in days if e["date"] == d(0))
    assert (mon1["weights"][ex["exercise_id"]]["logged_reps"], mon1["weights"][ex["exercise_id"]]["logged_lb"]) == (9, 15)
    mon3 = next(e for e in days if e["date"] == d(14))                           # the same day, 2 weeks later
    assert mon3["weights"][ex["exercise_id"]]["suggested_lb"] == 17.5            # 15 logged + 2.5 lb (arms)


def test_losing_weight_goes_up_5_lb_when_the_four_week_pattern_starts_again(client, on_day):
    uid, h = account(client, "loser", goal="lose_weight", experience_level="intermediate", equipment=["dumbbells"],
                     injuries=["none"])
    on_day(MONDAY + timedelta(days=28))                                          # 4 weeks on: the calendar tops up
    days = workout_days(weeks(client, h, 5))
    on_day(MONDAY)
    w1 = next(e for e in days if e["date"] == d(0))
    w5 = next(e for e in days if e["date"] == (MONDAY + timedelta(days=28)).isoformat())
    assert w1["workout"]["week_in_block"] == w5["workout"]["week_in_block"] == 1
    ex = first_weighted(w1)
    assert w1["weights"][ex["exercise_id"]]["suggested_lb"] == 10 and w5["weights"][ex["exercise_id"]]["suggested_lb"] == 15


def test_feeling_good_never_raises_a_weight_by_itself(client, on_day):
    uid, h = account(client, "steady", goal="feel_good", experience_level="intermediate", equipment=["dumbbells"],
                     injuries=["none"])
    on_day(MONDAY + timedelta(days=28))
    days = workout_days(weeks(client, h, 8))
    suggested = {i["suggested_lb"] for e in days for i in e["weights"].values() if i["weighted"]}
    assert suggested and suggested <= {10, 20}                                    # only the defaults, ever


def test_beginners_start_with_no_number_then_build_on_their_first_log(client, on_day):
    uid, h = account(client, "newbie", goal="stronger", experience_level="beginner", equipment=["dumbbells"],
                     injuries=["none"])
    days = workout_days(weeks(client, h, 4))
    mon1 = next(e for e in days if e["date"] == d(0))
    ex = first_weighted(mon1)
    assert mon1["weights"][ex["exercise_id"]]["suggested_lb"] is None            # bodyweight only: their pick
    patch(client, h, mon1["id"], completed=True, log=[{"exercise_id": ex["exercise_id"], "reps": 10, "weight_lb": 8}])
    mon3 = next(e for e in workout_days(weeks(client, h, 4)) if e["date"] == d(14))
    assert mon3["weights"][ex["exercise_id"]]["suggested_lb"] == 10.5           # 8 + 2.5


def test_injured_users_progress_by_their_goals_rule_too(client, on_day):
    """Decision 2026-10-25 (shared_rules.md rule 8): weights go up for everyone; the injury filter still decides the
    exercises."""
    uid, h = account(client, "hurt", **{**STRONG, "injuries": ["knee"]})
    days = workout_days(weeks(client, h, 4))
    mon1, mon3 = (next(e for e in days if e["date"] == d(n)) for n in (0, 14))
    ex = first_weighted(mon1)
    assert mon3["weights"][ex["exercise_id"]]["suggested_lb"] == mon1["weights"][ex["exercise_id"]]["suggested_lb"] + 2.5


def test_logging_stores_reps_and_only_real_weights(client, on_day):
    uid, h = account(client, "logger", **STRONG)
    mon1 = next(e for e in workout_days(weeks(client, h, 1)) if e["date"] == d(0))
    body = next(x for x in mon1["workout"]["exercises"] if not mon1["weights"][x["exercise_id"]]["weighted"])
    heavy = first_weighted(mon1)
    assert patch(client, h, mon1["id"], completed=True,
                 log=[{"exercise_id": "made_up", "reps": 5}]).status_code == 422          # not on this day
    r = patch(client, h, mon1["id"], completed=True, log=[
        {"exercise_id": body["exercise_id"], "reps": 12, "weight_lb": 99},                # bodyweight: weight ignored
        {"exercise_id": heavy["exercise_id"], "reps": 8, "weight_lb": 12.5}])
    assert r.status_code == 200
    logged = {r["exercise_id"]: r for r in rows("SELECT exercise_id, reps, weight_used FROM workout_logs "
                                                "WHERE calendar_entry_id = ?", mon1["id"])}
    assert (logged[body["exercise_id"]]["reps"], logged[body["exercise_id"]]["weight_used"]) == (12, None)
    assert (logged[heavy["exercise_id"]]["reps"], logged[heavy["exercise_id"]]["weight_used"]) == (8, 12.5)
    assert len(logged) == len(mon1["workout"]["exercises"])                             # one row per exercise
    patch(client, h, mon1["id"], completed=False)
    assert rows("SELECT COUNT(*) AS n FROM workout_logs WHERE calendar_entry_id = ?", mon1["id"]) == [{"n": 0}]


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

    retake(client, uid, h, experience_level="intermediate")
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

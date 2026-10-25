"""The calendar redesign: a day-type choice on every open day, cardio with minutes / steps / distance and a code-only
calorie estimate, calories on done days, and the progress marker. No AI anywhere in it.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_calendar_redesign.py -v

Every calorie and pound figure here is checked against a hand calculation (165 lb = 74.84 kg; kcal = MET x kg x
hours; Compendium codes in app/services/cardio_estimate.py), so a change to the math has to change these numbers.
"""

import math
from datetime import date

import pytest

from app.services.cardio_estimate import estimate_cardio
from app.services.workout_review import estimate
from tests.helpers import quiz_answers
from tests.test_agents import rows, use_script  # noqa: F401  (fixture)
from tests.test_calendar import MONDAY, account, by_date, d, get_days, on_day, patch  # noqa: F401  (on_day: fixture)

KG = 165 * 0.45359237   # the test profile's weight (tests/helpers.py quiz_answers)


# ================================================================ 1. the cardio estimate (pure code)

def test_minutes_use_the_types_low_and_high_compendium_codes():
    e = estimate_cardio("walking", minutes=30, weight_lb=165)
    # 3.0 MET (17170) x 74.84 kg x 0.5 h = 112.3 -> 110 (rounded down); 5.5 MET (17220) -> 205.8 -> 210 (rounded up)
    assert e["kcal"] == {"low": 110, "high": 210} and not e["rough"]
    assert (e["method"]["low"]["code"], e["method"]["high"]["code"]) == ("17170", "17220")
    swim = estimate_cardio("swimming", minutes=45, weight_lb=165)
    assert swim["kcal"] == {"low": 265, "high": 555}    # 4.8 x 74.84 x .75 = 269.4 -> 265; 9.8 -> 550.1 -> 555


def test_distance_uses_calories_per_mile_from_the_codes_that_state_a_speed():
    e = estimate_cardio("running", miles=3, weight_lb=165)
    # MET / mph across 12028..12090: lowest 9.3/6.3 = 1.476, highest 8.5/5.0 = 1.70 kcal per kg per mile
    assert (9.3 / 6.3 * KG * 3, 8.5 / 5.0 * KG * 3) == pytest.approx((331.4, 381.7), abs=0.1)
    assert e["kcal"] == {"low": 330, "high": 385}                                 # rounded outward to 5
    assert estimate_cardio("swimming", miles=1, weight_lb=165)["available"] is False   # no speed codes: minutes only


def test_steps_are_extra_rough_and_walking_only():
    e = estimate_cardio("walking", steps=5000, weight_lb=165)
    # 5,000 steps at 2,500-2,000 steps a mile = 2.0-2.5 miles; walking 3.8/3.4 = 1.118 to 5.5/4.0 = 1.375 per kg-mile
    assert e["kcal"] == {"low": 165, "high": 260} and e["rough"] is True
    assert any("2,000 to 2,500 steps" in c for c in e["caveats"])
    assert estimate_cardio("running", steps=5000, weight_lb=165)["available"] is False


def test_no_number_when_we_cant_give_a_fair_one():
    assert estimate_cardio("other", minutes=30, weight_lb=165)["available"] is False
    assert estimate_cardio(None, minutes=30, weight_lb=165)["available"] is False
    assert estimate_cardio("walking", minutes=30, weight_lb=None)["available"] is False


# ================================================================ 2. logging cardio through the API

def log(client, h, **body):
    return client.post("/api/cardio", headers=h, json={"date": d(1), **body})


def test_log_cardio_by_minutes_steps_or_distance_with_a_code_only_estimate(client, on_day, use_script):
    script = use_script(("final", {"encouragement": "x", "fun_fact_comparison": None}))
    uid, h = account(client, "measures")
    walk = log(client, h, activity="evening walk", cardio_type="walking", measure="steps", steps=5000).json()
    assert walk["log"]["estimate"]["kcal"] == {"low": 165, "high": 260} and walk["agent_called"] is False
    run = log(client, h, activity="park run", cardio_type="running", measure="distance", distance=4.828,
              distance_unit="km").json()                                  # 4.828 km = 3.0 miles
    assert run["log"]["distance_miles"] == 3.0 and run["log"]["estimate"]["kcal"] == {"low": 330, "high": 385}
    rope = log(client, h, exercise_id="Rope_Jumping", measure="duration", duration_minutes=10).json()
    assert rope["log"]["cardio_type"] == "jump_rope"                      # a library pick decides the type
    assert rope["log"]["estimate"]["kcal"] == {"low": 110, "high": 140}  # 9.0 x 74.84 / 6 = 112.3; 11.0 -> 137.2
    assert script.calls == 0 and rows("SELECT COUNT(*) AS n FROM agent_runs") == [{"n": 0}]

    assert log(client, h, activity="x", cardio_type="running", measure="steps", steps=100).status_code == 422
    assert log(client, h, activity="x", cardio_type="swimming", measure="distance", distance=1).status_code == 422
    assert log(client, h, activity="x", measure="duration").status_code == 422                  # nothing measured
    assert log(client, h, activity="x", measure="duration", duration_minutes=5, steps=10).status_code == 422
    other = log(client, h, activity="roller derby", cardio_type="other", duration_minutes=30).json()
    assert other["log"]["estimate"]["available"] is False                # no fair MET value: no number


def test_pregnant_users_log_cardio_any_way_they_like_but_get_no_numbers(client, on_day):
    """Decision (shared_rules.md rule 9, extended 2026-10-23): pregnant / postpartum users can log cardio by minutes,
    steps or distance, in their own words. No calorie estimate and no progress marker, and still no library picker."""
    uid, h = account(client, "expecting", pregnancy_status="pregnant")
    for body in ({"measure": "duration", "duration_minutes": 20}, {"measure": "steps", "steps": 4000},
                 {"measure": "distance", "distance": 1.5}):
        r = log(client, h, activity="walk my midwife okayed", cardio_type="walking", **body)
        assert r.status_code == 201, r.text
        assert r.json()["log"]["estimate"]["available"] is False
    assert all(not c["estimate"]["available"] for c in get_days(client, h)["cardio"])
    assert log(client, h, exercise_id="Walking_Treadmill", duration_minutes=20).status_code == 403
    assert client.get("/api/calendar/progress", headers=h).json()["available"] is False
    assert rows("SELECT COUNT(*) AS n FROM workout_logs WHERE user_id = ?", uid) == [{"n": 3}]   # it still counts


# ================================================================ 3. the day-type choice

def days(client, h):
    return by_date(get_days(client, h))


def test_every_open_day_offers_plan_build_or_cardio(client, on_day):
    uid, h = account(client, "chooser")
    cal = days(client, h)
    rest = next(e for e in cal.values() if e["day_type"] == "rest" and e["date"] > d(1))
    workout = next(e for e in cal.values() if e["day_type"] == "workout")
    assert rest["choice"] == workout["choice"] == "plan" and rest["can_override"]

    # "Add cardio" on a future rest day: a cardio day, not done until cardio is logged on it
    r = client.post(f"/api/calendar/{rest['id']}/cardio-day", headers=h, json={"cardio_type": "cycling"})
    assert r.status_code == 200 and r.json()["agent_called"] is False
    day = r.json()["entry"]
    assert (day["day_type"], day["choice"], day["source"], day["completed"]) == ("cardio", "cardio", "custom", False)
    assert day["workout"]["focus"] == "Cardio: Cycling (outdoors)"
    assert patch(client, h, rest["id"], completed=True).status_code == 422          # done by logging, not a tick

    # its day comes: logging cardio marks it done and its calories show on the card
    on_day(date.fromisoformat(rest["date"]))
    logged = log(client, h, date=rest["date"], activity="ride", cardio_type="cycling", duration_minutes=40).json()
    assert logged["calendar_entry_updated"] == rest["id"]
    day = days(client, h)[rest["date"]]
    assert day["completed"] is True
    # 4.0 x 74.84 x 40/60 = 199.6 -> 195; 10.0 -> 498.9 -> 500
    assert (day["calories"]["low"], day["calories"]["high"]) == (195, 500)
    assert rows("SELECT COUNT(*) AS n FROM workout_logs WHERE user_id = ? AND date = ?", uid, rest["date"]) == [{"n": 1}]

    # remove the log: not done any more; then "Use my plan" brings the planned rest day back
    assert client.delete(f"/api/cardio/{logged['log']['id']}", headers=h).json()["calendar_entry_updated"] == rest["id"]
    assert days(client, h)[rest["date"]]["completed"] is False
    back = client.post(f"/api/calendar/{rest['id']}/use-plan", headers=h).json()["entry"]
    assert (back["day_type"], back["choice"], back["source"]) == ("rest", "plan", "generated")
    assert client.post(f"/api/calendar/{rest['id']}/use-plan", headers=h).status_code == 409   # already the plan


def test_logging_cardio_on_a_planned_rest_day_turns_it_into_a_done_cardio_day(client, on_day):
    uid, h = account(client, "restcardio")
    rest = next(e for e in days(client, h).values() if e["day_type"] == "rest" and e["date"] <= d(1))
    log(client, h, date=rest["date"], activity="walk", cardio_type="walking", duration_minutes=30)
    day = days(client, h)[rest["date"]]
    assert (day["day_type"], day["completed"], day["source"]) == ("cardio", True, "custom")
    assert (day["calories"]["low"], day["calories"]["high"]) == (110, 210)
    assert day["planned"]["day_type"] == "rest"                                 # "Use my plan" can bring it back


def test_a_done_strength_day_shows_the_reviewers_per_session_range(client, on_day):
    uid, h = account(client, "strengthcal")
    workout = next(e for e in days(client, h).values() if e["day_type"] == "workout" and e["date"] <= d(1))
    assert workout["calories"] is None                                          # not done yet: no number
    patch(client, h, workout["id"], completed=True)
    day = days(client, h)[workout["date"]]
    want = estimate(workout["workout"]["est_minutes"], 165, None, None)["per_session_kcal"]
    assert {k: day["calories"][k] for k in ("low", "high")} == want             # the exact same calculation


def test_use_my_plan_fills_an_open_day_in_build_it_myself_mode(client, on_day):
    uid, h = account(client, "selfmode")
    assert client.put("/api/calendar/mode", headers=h, json={"mode": "self"}).status_code == 200
    open_day = next(e for e in days(client, h).values() if e["date"] >= d(0) and e["choice"] == "open")
    r = client.post(f"/api/calendar/{open_day['id']}/use-plan", headers=h)
    assert r.status_code == 200
    filled = r.json()["entry"]
    assert filled["choice"] == "plan" and not filled["workout"].get("open")


def test_pregnant_users_get_no_day_choices(client, on_day):
    uid, h = account(client, "nochoice")
    entry = next(iter(days(client, h).values()))
    client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "t",
        "answers": quiz_answers(pregnancy_status="pregnant")})
    for path in ("cardio-day", "use-plan"):
        assert client.post(f"/api/calendar/{entry['id']}/{path}", headers=h, json={}).status_code == 403


# ================================================================ 4. the progress marker

def test_the_progress_marker_only_adds_up_numbers_the_code_already_computed(client, on_day, use_script):
    script = use_script(("final", {"encouragement": "x", "fun_fact_comparison": None}))
    uid, h = account(client, "progress")                                       # goal: losing weight, 165 lb
    cal = days(client, h)
    week = [e for e in cal.values() if e["date"] <= d(6)]
    workout = next(e for e in week if e["day_type"] == "workout" and e["date"] <= d(1))
    patch(client, h, workout["id"], completed=True)
    rest = next(e for e in week if e["day_type"] == "rest" and e["date"] <= d(1))
    log(client, h, date=rest["date"], activity="walk", cardio_type="walking", duration_minutes=30)

    p = client.get("/api/calendar/progress", headers=h, params={"week_start": MONDAY.isoformat()}).json()
    assert p["available"] and p["computed_by"] == "code" and p["agent_called"] is False and script.calls == 0
    items = {i["kind"]: i for i in p["items"]}

    strength = estimate(workout["workout"]["est_minutes"], 165, None, None)["per_session_kcal"]
    done = {"low": strength["low"] + 110, "high": strength["high"] + 210}       # + the 30-minute walk
    assert items["energy"]["value"]["kcal"] == done
    planned = [e for e in week if e["day_type"] in ("workout", "cardio")] + [rest]
    assert items["sessions"]["value"] == {"done": 2, "planned": len(planned)}

    # pounds: the done days plus the rest of this week's planned workouts, / 3,500, rounded outward
    later = [e for e in week if e["day_type"] == "workout" and e["id"] != workout["id"] and e["date"] >= d(0)]
    rest_of_week = [estimate(e["workout"]["est_minutes"], 165, None, None)["per_session_kcal"] for e in later]
    total = {"low": done["low"] + sum(k["low"] for k in rest_of_week),
             "high": done["high"] + sum(k["high"] for k in rest_of_week)}
    wc = items["weight_change"]["value"]
    assert wc["kcal"] == total
    assert wc["pounds"] == {"low": math.floor(total["low"] / 3500 * 10) / 10, "high": math.ceil(total["high"] / 3500 * 10) / 10}
    assert "rough approximation, not a prediction" in items["weight_change"]["text"]
    assert items["weight_change"]["anchor"] == "calorie-estimates"
    for item in p["items"]:                                                     # tone: never about food or bodies
        assert not any(w in item["text"].lower() for w in ("diet", "eat", "food", "fat", "body", "skinny"))


def test_other_goals_get_no_calorie_or_pound_lines(client, on_day):
    """Weight is only asked when the goal is losing weight, so other goals have no weight to do calorie math with: the
    marker shows the days done and minutes, never a calorie or pound figure (and the done day has no calorie chip)."""
    uid, h = account(client, "strongonly", goal="stronger", injuries=["none"])
    workout = next(e for e in days(client, h).values() if e["day_type"] == "workout" and e["date"] <= d(1))
    patch(client, h, workout["id"], completed=True)
    kinds = {i["kind"] for i in client.get("/api/calendar/progress", headers=h).json()["items"]}
    assert "sessions" in kinds and not kinds & {"energy", "weight_change"}
    assert days(client, h)[workout["date"]]["calories"] is None

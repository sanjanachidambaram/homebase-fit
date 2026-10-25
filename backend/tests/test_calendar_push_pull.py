"""The plan's repeating weeks through the CALENDAR paths, not just the generator.

Calendar days are made by different entry points: saving or retaking the quiz (materialize_plan) and GET
/api/calendar's top-up when no future days are left. Each must lay out, for every date, exactly the generator's day
for that week of the goal's 2-, 4- or 8-week pattern, with Upper and Lower days never mixed. (This file used to test
the old Push/Pull split, retired in the 2026-10-25 rewrite; the property it protected, that the calendar shows the
same days the generator built, is what's tested now.)

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_calendar_push_pull.py -v
"""

from datetime import date, timedelta

from app.calendar import plan_day_on, plan_week
from app.services.program_generator import generate_for_user
from tests.test_agents import rows
from tests.test_calendar import MONDAY, account, get_days, on_day, patch, retake  # noqa: F401

UPPER = {"chest", "shoulders", "arms", "back"}


def four_weeks(client, h, start=MONDAY):
    return get_days(client, h, start, start + timedelta(days=27))["entries"]


def started(uid) -> date:
    return date.fromisoformat(rows("SELECT plan_started_on FROM quiz_profiles WHERE user_id = ?", uid)[0]["plan_started_on"])


def assert_matches_the_generator(uid, entries):
    plan, start = generate_for_user(uid), started(uid)
    for e in entries:
        if e["source"] != "generated":
            continue
        pd = plan_day_on(plan, date.fromisoformat(e["date"]), start)
        assert e["workout"]["week"] == plan_week(date.fromisoformat(e["date"]), start)
        assert [x["exercise_id"] for x in e["workout"]["exercises"]] == [x.exercise_id for x in pd.exercises], e["date"]
        groups = {x["muscle_group"] for x in e["workout"]["exercises"]}
        if e["workout"].get("category") == "upper":
            assert groups <= UPPER, e["date"]
        if e["workout"].get("category") == "lower":
            assert groups == {"legs"}, e["date"]


def test_first_quiz_lays_out_each_week_of_the_pattern(client, on_day):
    uid, h = account(client, "first", goal="stronger", experience_level="intermediate", equipment=["dumbbells"],
                     injuries=["none"])
    entries = four_weeks(client, h)
    assert_matches_the_generator(uid, entries)
    focus = {(e["workout"]["week"], e["weekday"]): e["workout"]["focus"] for e in entries if e["day_type"] == "workout"}
    assert (focus[(1, "mon")], focus[(2, "mon")], focus[(3, "mon")]) == ("Upper body", "Lower body", "Upper body")


def test_a_retake_into_another_goal_lays_out_its_pattern(client, on_day):
    uid, h = account(client, "switch", goal="feel_good", injuries=["none"])
    on_day(MONDAY + timedelta(days=2))
    retake(client, uid, h, goal="lose_weight", experience_level="intermediate", equipment=["dumbbells"], injuries=["none"])
    entries = four_weeks(client, h, MONDAY + timedelta(days=2))
    assert_matches_the_generator(uid, entries)
    cats = [e["workout"].get("category") for e in entries if e["day_type"] == "workout"]
    assert "mobility" not in cats and cats.count("cardio") == 2 * cats.count("upper")   # losing weight: 2 + 2


def test_the_calendar_top_up_keeps_counting_the_pattern(client, on_day):
    uid, h = account(client, "topup", goal="lose_weight", experience_level="intermediate", equipment=["dumbbells"],
                     injuries=["none"])
    on_day(MONDAY + timedelta(days=28))                                       # 4 weeks on: nothing left ahead
    entries = four_weeks(client, h, MONDAY + timedelta(days=28))
    assert {e["workout"]["week"] for e in entries} == {5, 6, 7, 8}
    assert {e["workout"].get("week_in_block") for e in entries} == {1, 2, 3, 4}   # weeks 5-8 repeat weeks 1-4
    assert_matches_the_generator(uid, entries)


def test_a_retake_keeps_the_users_own_days(client, on_day):
    uid, h = account(client, "keepmine", goal="stronger", injuries=["none"])
    days = {e["date"]: e for e in four_weeks(client, h)}
    done = days[MONDAY.isoformat()]
    patch(client, h, done["id"], completed=True)
    retake(client, uid, h, goal="feel_good", injuries=["none"])
    after = {e["date"]: e for e in four_weeks(client, h)}
    assert after[MONDAY.isoformat()]["workout"]["exercises"] == done["workout"]["exercises"]   # done day kept
    assert_matches_the_generator(uid, [e for d, e in after.items() if d > MONDAY.isoformat()])

"""Every plan runs 6 months (26 weeks, 182 days), decided 2026-10-25.

The plan is stored as its repeating pattern plus the day it started; calendar days are laid out the first time
they're viewed. These tests walk the whole 6 months through the real calendar API and check: every one of the 182
days is there (no gaps, nothing before or after), every week has its 4 training days and none is empty, the
rotation keeps cycling (not week 1 forever), the suggested weights climb by the goal's rule across all 26 weeks
with no reset, today's workout comes from anywhere in the plan, and nothing is pre-expanded or oversized.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_six_month_plan.py -v
"""

import json
from collections import Counter, defaultdict
from datetime import date, timedelta

import pytest

from app import calendar
from app.services import program_generator as gen
from app.services.program_generator import BLOCK_WEEKS, PLAN_DAYS, PLAN_WEEKS
from tests.test_agents import rows
from tests.test_calendar import MONDAY, account, get_days, on_day  # noqa: F401  (on_day is a fixture)

PROFILES = {
    "stronger": dict(goal="stronger", experience_level="intermediate", equipment=["dumbbells"], injuries=["none"]),
    "lose_weight": dict(goal="lose_weight", experience_level="intermediate", equipment=["dumbbells"], injuries=["none"]),
    "feel_good": dict(goal="feel_good", experience_level="advanced", equipment=["dumbbells"], injuries=["none"]),
}


def whole_plan(client, h, start=MONDAY) -> list[dict]:
    """All 182 days, fetched the way the calendar does (at most 62 days per request), plus a week either side."""
    out, d = [], start - timedelta(days=7)
    last = start + timedelta(days=PLAN_DAYS + 6)
    while d <= last:
        end = min(d + timedelta(days=55), last)
        out += get_days(client, h, d, end)["entries"]
        d = end + timedelta(days=1)
    return out


def test_six_months_is_26_weeks():
    assert (PLAN_WEEKS, PLAN_DAYS) == (26, 182)
    assert calendar.plan_end(MONDAY) == MONDAY + timedelta(days=181)


@pytest.mark.parametrize("goal", list(PROFILES))
def test_every_day_of_the_six_months_is_there_with_no_gaps(client, on_day, goal):
    uid, h = account(client, f"full-{goal}", **PROFILES[goal])
    entries = whole_plan(client, h)
    dates = [e["date"] for e in entries]
    want = [(MONDAY + timedelta(days=i)).isoformat() for i in range(PLAN_DAYS)]
    assert dates == want                                             # every day, once, in order: no gaps
    assert len(set(dates)) == PLAN_DAYS                              # nothing before the start or after the end
    weeks = defaultdict(list)
    for e in entries:
        weeks[e["workout"].get("week") or calendar.plan_week(date.fromisoformat(e["date"]), MONDAY)].append(e)
    assert sorted(weeks) == list(range(1, PLAN_WEEKS + 1))
    for week, days in weeks.items():
        kinds = Counter(e["day_type"] for e in days)
        assert kinds["workout"] + kinds["cardio"] == 4 and kinds["rest"] == 3, (goal, week, kinds)
        for e in days:
            if e["day_type"] == "workout":                           # no empty training days
                assert len(e["workout"]["exercises"]) >= 4, (goal, e["date"])
            if e["day_type"] == "cardio":
                assert e["workout"]["focus"] == "Cardio of your choice", (goal, e["date"])


@pytest.mark.parametrize("goal", list(PROFILES))
def test_the_rotation_keeps_cycling_for_all_26_weeks(client, on_day, goal):
    uid, h = account(client, f"rotate-{goal}", **PROFILES[goal])
    block = BLOCK_WEEKS[goal]
    day = {(e["workout"]["week"], e["weekday"]): [x["exercise_id"] for x in e["workout"]["exercises"]]
           for e in whole_plan(client, h) if e["day_type"] == "workout"}
    for (week, wd), ids in day.items():
        later = (week + block, wd)
        if later in day:
            assert day[later] == ids, (goal, week, wd)               # week w and w + block are the same day
    # ...and it's the goal's pattern, not week 1 on repeat: the weeks of a block differ where the library allows
    distinct = {tuple(ids) for (week, wd), ids in day.items() if wd == "mon"}
    assert len(distinct) > 1, goal
    assert {e["workout"]["week_in_block"] for e in whole_plan(client, h) if e["day_type"] != "rest"} == \
        set(range(1, block + 1))


def climb(entries) -> dict[str, list[tuple[int, float]]]:
    """Each weighted exercise's suggested weight, in plan order: [(week, lb), ...]."""
    out = defaultdict(list)
    for e in entries:
        for ex_id, info in e["weights"].items():
            if info["weighted"] and info["suggested_lb"] is not None:
                out[ex_id].append((e["workout"]["week"], info["suggested_lb"]))
    return out


def test_getting_stronger_climbs_every_time_a_day_comes_round_for_26_weeks(client, on_day):
    uid, h = account(client, "climb-stronger", **PROFILES["stronger"])
    loads = {x.exercise_id: x.load for w in gen.generate_for_user(uid).weeks for d in w.days for x in d.exercises}
    for ex_id, seen in climb(whole_plan(client, h)).items():
        by_week = dict(seen)                                         # twice in one week (Mon and Fri): same weight
        assert all(by_week[wk] == lb for wk, lb in seen), (ex_id, seen)
        lbs = [by_week[wk] for wk in sorted(by_week)]
        step = gen.WEIGHT_STEP_LB["stronger"][loads[ex_id]]
        assert all(b - a == step for a, b in zip(lbs, lbs[1:])), (ex_id, seen)   # up each week it's on, no reset
        assert lbs[0] == gen.DEFAULT_WEIGHT_LB["intermediate"][loads[ex_id]]
        assert seen[-1][0] >= PLAN_WEEKS - 1                         # carried right to the end of the 6 months


def test_losing_weight_adds_5_lb_each_new_block_for_26_weeks(client, on_day):
    uid, h = account(client, "climb-lose", **PROFILES["lose_weight"])
    for ex_id, seen in climb(whole_plan(client, h)).items():
        first = seen[0][1]
        for week, lb in seen:
            assert lb == first + 5 * ((week - 1) // 4), (ex_id, week, lb)   # weeks 25-26 are block 7: +30 lb
        assert [b - a for a, b in zip([lb for _, lb in seen], [lb for _, lb in seen][1:])] == \
            [5] * (len(seen) - 1) or all(b >= a for (_, a), (_, b) in zip(seen, seen[1:]))   # never goes down


def test_feeling_good_stays_where_it_starts_for_26_weeks(client, on_day):
    uid, h = account(client, "climb-feel", **PROFILES["feel_good"])
    for ex_id, seen in climb(whole_plan(client, h)).items():
        assert len({lb for _, lb in seen}) == 1, (ex_id, seen)


def test_a_logged_weight_in_month_4_carries_forward_without_a_reset(client, on_day):
    """A manual override mid-plan becomes the anchor; the goal's rule continues from there to week 26."""
    uid, h = account(client, "anchor-late", **PROFILES["stronger"])
    entries = whole_plan(client, h)
    target = next(e for e in entries if e["workout"].get("week") == 14 and e["day_type"] == "workout"
                  and any(i["weighted"] for i in e["weights"].values()))
    ex_id = next(k for k, i in target["weights"].items() if i["weighted"])
    on_day(date.fromisoformat(target["date"]))
    log = [{"exercise_id": x["exercise_id"], "reps": 8, "weight_lb": 12.0 if x["exercise_id"] == ex_id else None}
           for x in target["workout"]["exercises"]]
    r = client.patch(f"/api/calendar/{target['id']}", headers=h, json={"completed": True, "log": log})
    assert r.status_code == 200, r.text
    after = [(wk, lb) for wk, lb in climb(whole_plan(client, h))[ex_id] if wk > 14]
    load = next(x.load for w in gen.generate_for_user(uid).weeks for d in w.days for x in d.exercises
                if x.exercise_id == ex_id)
    step = gen.WEIGHT_STEP_LB["stronger"][load]
    assert after and after[0][1] == 12.0 + step                      # builds on the logged 12 lb, not the default
    assert all(b - a == step for (_, a), (_, b) in zip(after, after[1:]))


def test_todays_workout_comes_from_anywhere_in_the_six_months(client, on_day):
    uid, h = account(client, "deep-today", **PROFILES["lose_weight"])
    late = on_day(MONDAY + timedelta(days=150))                      # week 22, never viewed before
    body = get_days(client, h, late, late)
    assert [e["date"] for e in body["entries"]] == [late.isoformat()]
    assert body["entries"][0]["workout"]["week"] == 22
    assert body["plan"] == {"started_on": MONDAY.isoformat(), "ends_on": (MONDAY + timedelta(days=181)).isoformat(),
                            "weeks": 26, "current_week": 22, "ended": False}


def test_after_six_months_the_plan_has_ended(client, on_day):
    uid, h = account(client, "ended", **PROFILES["feel_good"])
    after = on_day(MONDAY + timedelta(days=PLAN_DAYS))               # day 183
    body = get_days(client, h, after, after + timedelta(days=6))
    assert body["entries"] == [] and body["plan"]["ended"] is True and body["plan"]["current_week"] == 26
    assert client.get("/api/plan", headers=h).json()["window"]["ended"] is True


def test_a_retake_starts_a_new_six_months(client, on_day):
    uid, h = account(client, "retake6", **PROFILES["stronger"])
    later = on_day(MONDAY + timedelta(days=100))
    from tests.test_calendar import retake
    retake(client, uid, h, **PROFILES["lose_weight"])
    body = get_days(client, h, later, later)
    assert body["plan"]["started_on"] == later.isoformat() and body["plan"]["current_week"] == 1
    assert body["plan"]["ends_on"] == (later + timedelta(days=181)).isoformat()


# ---------------------------------------------------------------- efficiency

def test_only_viewed_days_are_stored_and_complete_ranges_skip_generation(client, on_day, monkeypatch):
    uid, h = account(client, "lazy", **PROFILES["stronger"])
    count = lambda: rows("SELECT COUNT(*) AS n FROM calendar_entries WHERE user_id = ?", uid)[0]["n"]  # noqa: E731
    assert count() == 28                                            # the quiz lays out the first 4 weeks only
    calls = []
    real = calendar.generate_for_user
    monkeypatch.setattr(calendar, "generate_for_user", lambda *a, **k: calls.append(1) or real(*a, **k))
    get_days(client, h, MONDAY, MONDAY + timedelta(days=27))         # already there: no generation at all
    assert calls == [] and count() == 28
    week20 = MONDAY + timedelta(weeks=19)
    get_days(client, h, week20, week20 + timedelta(days=6))          # a new week: generated once, 7 rows added
    assert len(calls) == 1 and count() == 35


def test_payloads_stay_small(client, on_day):
    uid, h = account(client, "size", **PROFILES["stronger"])
    plan = client.get("/api/plan", headers=h)
    assert len(plan.content) < 64 * 1024                             # the pattern + a 26-week weight schedule
    assert plan.json()["plan_weeks"] == 26 and plan.json()["weights"]["schedule_weeks"] == 26
    assert len(plan.json()["weeks"]) == BLOCK_WEEKS["stronger"]      # the pattern, not 26 expanded weeks
    whole_plan(client, h)
    stored = rows("SELECT SUM(LENGTH(workout_content)) AS n FROM calendar_entries WHERE user_id = ?", uid)[0]["n"]
    assert stored < 512 * 1024                                       # all 182 days, even fully browsed
    assert json.loads(rows("SELECT workout_content FROM calendar_entries WHERE user_id = ? LIMIT 1", uid)[0]
                      ["workout_content"])["plan_day"]

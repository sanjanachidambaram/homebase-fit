"""The Dashboard's "This week" card (app/services/weekly_summary.py, GET /api/progress/this-week): workouts logged this
week (Monday to today) and one fun fact, built by code from what was logged, reusing the Coach's comparisons.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_weekly_summary.py -v
"""

import random
from datetime import date

from app.db import connect
from app.mcp_server.strength import COMPARISONS
from app.services.weekly_summary import DISTANCES, weekly_summary
from tests.test_calendar import on_day  # noqa: F401  (fixture: freezes the calendar's today)

THURSDAY = date(2026, 10, 22)          # its week: Monday 2026-10-19 to Sunday 2026-10-25


def user(username="weekly") -> int:
    conn = connect()
    with conn:
        uid = conn.execute("INSERT INTO users (username, password_hash) VALUES (?, 'x')", (username,)).lastrowid
    conn.close()
    return uid


def log(uid, day, sets=None, reps=None, weight=None, exercise="goblet_squat"):
    conn = connect()
    with conn:
        conn.execute("INSERT INTO workout_logs (user_id, date, exercise_id, sets, reps, weight_used) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (uid, day, exercise, sets, reps, weight))
    conn.close()


def cardio(uid, day, **measure):
    kind = next(iter(measure))
    column = {"steps": "steps", "distance": "distance_miles", "duration": "duration_minutes"}[kind]
    conn = connect()
    with conn:
        conn.execute(f"INSERT INTO cardio_logs (user_id, date, activity, measure, {column}) VALUES (?, ?, 'walk', ?, ?)",
                     (uid, day, kind, measure[kind]))
        conn.execute("INSERT INTO workout_logs (user_id, date, duration_seconds) VALUES (?, ?, 600)", (uid, day))
    conn.close()


def test_counts_the_days_with_a_workout_this_week_only(test_db):
    uid = user()
    log(uid, "2026-10-18", 3, 10, 20)                     # last Sunday: last week
    log(uid, "2026-10-19", 3, 10, 20)                     # Monday
    log(uid, "2026-10-19", 2, 12, 15, exercise="dead_bug")   # same day, second exercise: still one workout
    log(uid, "2026-10-21", 3, 10, 20)                     # Wednesday
    log(uid, "2026-10-24", 3, 10, 20)                     # Saturday: later this week, not happened yet
    s = weekly_summary(uid, THURSDAY, random.Random(1))
    assert (s["week_start"], s["week_end"]) == ("2026-10-19", "2026-10-25")
    assert s["workouts_logged"] == 2
    assert s["weight_lifted_lbs"] == 600 + 360 + 600      # sets x reps x weight, Monday to today


def test_weight_moved_gives_the_coachs_strength_comparison(test_db):
    uid = user()
    log(uid, "2026-10-20", 3, 10, 50)                     # 1,500 lb
    s = weekly_summary(uid, THURSDAY, random.Random(3))
    fact = s["fun_fact"]
    assert fact["kind"] == "lifted" and fact["text"].startswith("This week you've lifted about ")
    names = {c["name"]: c for c in COMPARISONS}
    picked = next(n for n in names if f" {n}!" in fact["text"] or f" {names[n]['singular']}!" in fact["text"])
    assert 1500 / names[picked]["unit_weight_lbs"] >= 1  # a thing the total actually reaches
    assert "You moved 1,500 lb this week" in fact["basis"] and s["note"].startswith("Just for fun")


def test_tiny_weight_says_a_fraction(test_db):
    uid = user()
    log(uid, "2026-10-20", 1, 1, 2)                       # 2 lb: less than one chihuahua
    assert weekly_summary(uid, THURSDAY)["fun_fact"]["text"] == \
        "This week you've lifted 0.40 of a chihuahua. Keep going!"


def test_steps_and_distance_become_a_distance_comparison(test_db):
    uid = user()
    cardio(uid, "2026-10-20", steps=4000)                 # 2 miles at 2,000 steps a mile
    cardio(uid, "2026-10-21", distance=1.0)
    s = weekly_summary(uid, THURSDAY, random.Random(0))
    assert s["workouts_logged"] == 2 and s["cardio_miles"] == 3.0
    fact = s["fun_fact"]
    assert fact["kind"] == "distance" and fact["text"].startswith("This week you've covered about ")
    assert any(d["name"] in fact["text"] or d["singular"] in fact["text"] for d in DISTANCES[-2:])
    assert fact["basis"].endswith("You covered 3.0 miles this week, counting steps at 2,000 per mile")


def test_minutes_only_become_soccer_matches(test_db):
    uid = user()
    cardio(uid, "2026-10-20", duration=45)
    assert weekly_summary(uid, THURSDAY)["fun_fact"]["text"] == \
        "This week you've moved for 45 minutes: 50% of a full soccer match. Keep going!"
    cardio(uid, "2026-10-21", duration=135)
    assert weekly_summary(uid, THURSDAY)["fun_fact"]["text"] == \
        "This week you've moved for 180 minutes: about 2.0 full soccer matches!"


def test_weights_win_over_cardio_for_the_fun_fact(test_db):
    uid = user()
    cardio(uid, "2026-10-20", steps=8000)
    log(uid, "2026-10-21", 3, 10, 30)
    assert weekly_summary(uid, THURSDAY)["fun_fact"]["kind"] == "lifted"


def test_nothing_logged_means_no_fact_and_a_nudge(test_db):
    s = weekly_summary(user(), THURSDAY)
    assert s["workouts_logged"] == 0 and s["fun_fact"] is None
    assert "unlock a fun fact" in s["note"]


def test_the_fun_facts_stay_on_objects_and_places(test_db):
    """shared_rules.md rule 5: never the person's body, food or body weight."""
    uid = user()
    cardio(uid, "2026-10-20", distance=5.0)
    cardio(uid, "2026-10-21", duration=60)
    log(uid, "2026-10-21", 3, 10, 40)
    texts = [weekly_summary(uid, THURSDAY, random.Random(i))["fun_fact"]["text"].lower() for i in range(20)]
    for word in ("calorie", "pizza", "burger", "body", "pounds of fat", "your weight"):
        assert not any(word in t for t in texts), word


def test_endpoint_is_signed_in_only_and_uses_the_calendars_today(client, on_day):
    assert client.get("/api/progress/this-week").status_code == 401
    r = client.post("/api/users", json={"username": "weekly_api", "first_name": "W", "password": "correct horse 1"})
    uid, h = r.json()["user_id"], {"Authorization": f"Bearer {r.json()['token']}"}
    on_day(THURSDAY)
    log(uid, "2026-10-19", 3, 10, 20)
    body = client.get("/api/progress/this-week", headers=h).json()
    assert body["week_start"] == "2026-10-19" and body["workouts_logged"] == 1 and body["fun_fact"]["kind"] == "lifted"

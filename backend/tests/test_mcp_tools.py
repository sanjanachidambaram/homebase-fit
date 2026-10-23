"""The MCP tool server: every tool, the injury guardrails, the PII boundary, and read-only access.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_mcp_tools.py -v

Tools are called through a real FastMCP client (in memory), against a throwaway copy of the database.
"""

import asyncio
import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from app import config
from app.db import connect, connect_readonly
from app.mcp_server import progress
from app.mcp_server.server import mcp

TODAY = datetime.now(timezone.utc).date()
EXPECTED_TOOLS = {"get_user_profile", "search_exercises", "search_basics_kb",
                  "get_progress_summary", "compute_strength_equivalents", "check_goal_achievement"}


def call(tool: str, **args):
    """Call an MCP tool the way an agent would; returns the structured result (raises ToolError on error)."""
    async def run():
        async with Client(mcp) as c:
            return (await c.call_tool(tool, args)).data
    return asyncio.run(run())


def day(n: int) -> str:
    """The date n days ago, as stored in the database."""
    return (TODAY - timedelta(days=n)).isoformat()


def make_user(username="private.person", first_name="Zenobia", goals=("weight_loss",), timeline="8_weeks", injuries=("lower_back",),
              quiz_days_ago=20, notes="Dr. Smith said L4 disc issue") -> int:
    conn = connect()
    with conn:
        uid = conn.execute("INSERT INTO users (username, first_name, password_hash) VALUES (?, ?, 'x')", (username, first_name)).lastrowid
        stamp = (datetime.now(timezone.utc) - timedelta(days=quiz_days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO quiz_profiles (user_id, goals, timeline, injury_flags, injury_notes, age, weight, height, "
            "consent_accepted, consent_accepted_at, consent_version, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 34, 165, 66, 1, ?, 'v1', ?, ?)",
            (uid, json.dumps(list(goals)), timeline, json.dumps(list(injuries)), notes, stamp, stamp, stamp))
    conn.close()
    return uid


def log(uid, days_ago, sets=3, reps=10, weight=20.0, exercise="glute_bridge"):
    conn = connect()
    with conn:
        conn.execute("INSERT INTO workout_logs (user_id, date, exercise_id, sets, reps, weight_used) "
                     "VALUES (?, ?, ?, ?, ?, ?)", (uid, day(days_ago), exercise, sets, reps, weight))
    conn.close()


def weigh(uid, days_ago, body_weight, **other):
    conn = connect()
    with conn:
        conn.execute("INSERT INTO measurements (user_id, date, body_weight, measurements) VALUES (?, ?, ?, ?)",
                     (uid, day(days_ago), body_weight, json.dumps(other)))
    conn.close()


def tag(exercise_id, contraindications, status="draft"):
    conn = connect()
    with conn:
        conn.execute("UPDATE exercises SET injury_contraindications = ?, contraindication_status = ? WHERE id = ?",
                     (json.dumps(contraindications), status, exercise_id))
    conn.close()


# ---------------------------------------------------------------- least privilege

def test_exactly_six_tools_all_read_only(test_db):
    async def run():
        async with Client(mcp) as c:
            return await c.list_tools()
    tools = asyncio.run(run())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False, t.name


def test_database_connection_cannot_write(test_db):
    conn = connect_readonly()
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM exercises")
    conn.close()


def test_running_every_tool_leaves_the_database_unchanged(test_db):
    uid = make_user()
    log(uid, 0)
    before = hashlib.sha256(test_db.read_bytes()).hexdigest()
    call("get_user_profile", user_id=uid)
    call("search_exercises", muscle_group="legs", injury_flags=["knee"])
    call("search_basics_kb", query="rest between sets")
    call("get_progress_summary", user_id=uid)
    call("compute_strength_equivalents", total_weight_lifted_lbs=1000)
    call("check_goal_achievement", user_id=uid)
    assert hashlib.sha256(test_db.read_bytes()).hexdigest() == before


# ---------------------------------------------------------------- 1. get_user_profile

def test_profile_returns_only_the_allowed_fields(test_db):
    uid = make_user()
    p = call("get_user_profile", user_id=uid)
    assert set(p) == {"found", "goals", "timeline", "injury_flags", "age", "weight_lb", "height_in"}
    assert p["goals"] == ["weight_loss"] and p["injury_flags"] == ["lower_back"] and p["timeline"] == "8_weeks"
    assert (p["age"], p["weight_lb"], p["height_in"]) == (34, 165, 66)


def test_profile_matches_the_shared_pii_boundary_function(test_db):
    from app.agents.context import agent_profile_for
    uid = make_user()
    assert {k: v for k, v in call("get_user_profile", user_id=uid).items() if k != "found"} == \
        agent_profile_for(uid).model_dump()


def test_profile_not_found_cases(test_db):
    assert call("get_user_profile", user_id=999)["found"] is False
    uid = make_user()
    conn = connect()
    with conn:
        conn.execute("DELETE FROM quiz_profiles WHERE user_id = ?", (uid,))
    conn.close()
    assert call("get_user_profile", user_id=uid)["found"] is False


def test_no_tool_ever_returns_username_name_or_notes(test_db):
    uid = make_user()
    log(uid, 0)
    weigh(uid, 5, 170.0)
    weigh(uid, 0, 166.0)
    outputs = [
        call("get_user_profile", user_id=uid), call("get_progress_summary", user_id=uid),
        call("check_goal_achievement", user_id=uid), call("search_exercises", injury_flags=["knee"]),
        call("search_basics_kb", query="injury"),
        call("compute_strength_equivalents", total_weight_lifted_lbs=5000),
    ]
    text = json.dumps(outputs).lower()
    for secret in ("private.person", "zenobia", "dr. smith", "l4 disc", "password"):
        assert secret not in text


# ---------------------------------------------------------------- 2. search_exercises

def test_injury_filter_excludes_tagged_exercises(test_db):
    tag("Adductor", ["knee"])                                   # an imported exercise, tagged for the test
    plain = call("search_exercises", muscle_group="legs", limit=50)
    assert "Adductor" in {e["id"] for e in plain["exercises"]}
    assert plain["injury_filter"]["applied"] is False

    filtered = call("search_exercises", muscle_group="legs", injury_flags=["knee"], limit=50)
    ids = {e["id"] for e in filtered["exercises"]}
    assert "Adductor" not in ids
    assert {"bodyweight_squat", "reverse_lunge", "wall_sit", "goblet_squat"}.isdisjoint(ids)   # drafted knee tags
    assert filtered["injury_filter"]["excluded_as_contraindicated"] == plain["total_matching"] - filtered["total_matching"] == 5
    for e in filtered["exercises"]:
        assert "knee" not in e["injury_contraindications"]


def test_any_matching_flag_excludes(test_db):
    tag("Adductor", ["shoulder"])
    ids = {e["id"] for e in call("search_exercises", muscle_group="legs", injury_flags=["knee", "shoulder"],
                                 limit=50)["exercises"]}
    assert "Adductor" not in ids


def test_unchecked_exercises_are_flagged_not_called_safe(test_db):
    res = call("search_exercises", muscle_group="chest", injury_flags=["shoulder"], limit=10)
    assert res["exercises"], "imported exercises should still be returned"
    for e in res["exercises"]:
        assert e["injury_check"] == "not_yet_checked" and e["injury_unchecked"] is True
        assert "not" in e["injury_note"].lower() and "safe" in e["injury_note"].lower()
        assert e["status"] == "placeholder" and e["review_notice"] == "Content pending expert review"
        assert e["citations"] == []
    assert res["injury_filter"]["unchecked_in_matching"] == res["total_matching"]
    assert "does not mean they are safe" in res["injury_filter"]["note"]


def test_checked_exercises_come_first_and_checked_only_works(test_db):
    res = call("search_exercises", muscle_group="legs", injury_flags=["knee"], limit=50)
    flags = [e["injury_unchecked"] for e in res["exercises"]]
    assert flags == sorted(flags), "checked (False) exercises must come before unchecked (True)"
    assert res["exercises"][0]["injury_check"] == "drafted_not_pt_reviewed"
    only = call("search_exercises", muscle_group="legs", injury_flags=["knee"], checked_only=True, limit=50)
    assert only["count"] == 2 and not any(e["injury_unchecked"] for e in only["exercises"])


def test_equipment_means_what_the_user_has(test_db):
    ids = {e["id"] for e in call("search_exercises", equipment=["dumbbells"], limit=50)["exercises"]}
    assert "dumbbell_bicep_curl" in ids and "glute_bridge" not in ids      # glute bridge needs a mat
    assert "burpee" in ids                                                  # bodyweight is always allowed
    assert "band_pull_apart" not in ids
    bodyweight = call("search_exercises", equipment=["bodyweight"], limit=50)["exercises"]
    assert bodyweight and all(e["equipment_needed"] == ["none"] for e in bodyweight)
    assert call("search_exercises", equipment=["Resistance Band"], muscle_group="arms")["count"] > 0   # alias


def test_limit_and_bad_arguments(test_db):
    res = call("search_exercises", limit=3)
    assert res["count"] == 3 and res["total_matching"] == 903 and "truncated" in res
    for bad in ({"limit": 0}, {"limit": 51}, {"muscle_group": "wings"}, {"injury_flags": ["elbow"]},
                {"equipment": ["jetpack"]}):
        with pytest.raises(ToolError):
            call("search_exercises", **bad)


# ---------------------------------------------------------------- 4. search_basics_kb

def test_basics_search_finds_the_right_article(test_db):
    res = call("search_basics_kb", query="How long should I rest between sets?")
    assert res["answerable"] and res["matches"][0]["slug"] == "rest_between_sets"
    assert res["matches"][0]["status"] == "placeholder" and res["matches"][0]["review_notice"]
    assert "30–90 seconds is common" in res["matches"][0]["content"]
    assert call("search_basics_kb", query="sharp pain, should I stop?")["matches"][0]["slug"] == "push_through_vs_stop"
    assert call("search_basics_kb", query="injuries")["matches"][0]["slug"] == "injury_prevention_basics"   # plural


def test_basics_search_says_so_when_nothing_matches(test_db):
    res = call("search_basics_kb", query="quantum astrophysics of black holes")
    assert res["answerable"] is False and res["matches"] == []
    assert "I don't have verified information" in res["message"]
    for bad in ("", "   ", "x" * 501):
        with pytest.raises(ToolError):
            call("search_basics_kb", query=bad)


# ---------------------------------------------------------------- 5. get_progress_summary

def test_progress_summary_numbers(test_db):
    uid = make_user()
    for d in (0, 1, 2):
        log(uid, d, sets=3, reps=10, weight=20)            # 600 lb a day
    log(uid, 20, sets=2, reps=5, weight=50)                # 500 lb, inside the window
    log(uid, 40, sets=5, reps=5, weight=100)               # outside the window
    log(uid, 0, sets=1, reps=15, weight=None, exercise="bird_dog")   # bodyweight: adds nothing
    weigh(uid, 25, 170.0, waist_in=32.0)
    weigh(uid, 0, 166.0, waist_in=31.0)
    s = call("get_progress_summary", user_id=uid)
    assert s["found"] and s["window"]["days"] == 30
    assert s["sessions_logged"] == 4 and s["exercise_entries"] == 5
    assert s["total_weight_lifted_lbs"] == 2300.0
    assert s["weight_lifted_last_15_days_lbs"] == 1800.0 and s["weight_lifted_prior_15_days_lbs"] == 500.0
    assert s["current_streak_days"] == 3 and s["rest_day_suggested"] is False
    assert s["last_workout_date"] == day(0)
    bw = s["body_weight_trend"]
    assert (bw["first"], bw["latest"], bw["change"], bw["direction"], bw["entries"]) == (170.0, 166.0, -4.0, "down", 2)
    assert s["other_measurement_trends"]["waist_in"]["change"] == -1.0
    assert call("get_progress_summary", user_id=999) == {"found": False, "message": "No such user."}


def test_streak_rules(test_db):
    uid = make_user()
    for d in range(1, 11):       # yesterday back 10 days; nothing today
        log(uid, d)
    s = progress.get_progress_summary(uid, TODAY)
    assert s["current_streak_days"] == 10 and s["rest_day_suggested"] is True     # today not over: still counts
    other = make_user("user_b")
    log(other, 0); log(other, 2)
    assert progress.get_progress_summary(other, TODAY)["current_streak_days"] == 1  # gap breaks it
    third = make_user("user_c")
    log(third, 5)
    assert progress.get_progress_summary(third, TODAY)["current_streak_days"] == 0  # nothing today or yesterday


# ---------------------------------------------------------------- 6. compute_strength_equivalents

def test_strength_equivalents(test_db):
    zero = call("compute_strength_equivalents", total_weight_lifted_lbs=0)
    assert zero["headline"] is None and zero["comparisons"] == []
    # below the smallest comparison (2026-10-23: a 5 lb chihuahua, previously a 16 lb bowling ball): a fraction of one
    assert call("compute_strength_equivalents", total_weight_lifted_lbs=3)["headline"].startswith(
        "You've lifted 0.60 of a chihuahua")
    cars = call("compute_strength_equivalents", total_weight_lifted_lbs=4354 * 3)
    by_name = {c["name"]: c for c in cars["comparisons"]}
    assert by_name["full-size cars"]["count"] == 3.0
    assert cars["headline_comparison"] == "adult elephants"       # 13,062 lb is just over one elephant (11,700 lb)
    big = call("compute_strength_equivalents", total_weight_lifted_lbs=25000)
    assert big["headline"] == "You've lifted about 2.1 adult elephants!"
    for c in big["comparisons"]:
        assert c["unit_weight_lbs"] > 0 and c["basis"] and c["source"].strip()
        assert abs(c["count"] - 25000 / c["unit_weight_lbs"]) < 0.01
    assert {c["name"] for c in big["comparisons"]} >= {"full-size trees", "adult elephants"}
    for bad in (-1, 2e9):
        with pytest.raises(ToolError):
            call("compute_strength_equivalents", total_weight_lifted_lbs=bad)


# ---------------------------------------------------------------- 7. check_goal_achievement

def test_goal_check_insufficient_data(test_db):
    assert call("check_goal_achievement", user_id=999)["status"] == "insufficient_data"
    young = make_user(quiz_days_ago=3)
    for d in range(3):
        log(young, d)
    res = call("check_goal_achievement", user_id=young)
    assert res["status"] == "insufficient_data" and "too early" in res["reasons"][0]


def test_goal_check_on_track_ahead_behind(test_db):
    # on track: 8_weeks target is 3 a week; 9 sessions over a 20-day-old quiz is ~3.2 a week
    ok = make_user("user_a", goals=("tone",), timeline="8_weeks", quiz_days_ago=20)
    for d in (0, 2, 4, 6, 8, 10, 12, 14, 16):
        log(ok, d)
    r = call("check_goal_achievement", user_id=ok)
    assert r["status"] == "on_track" and r["checks"][0]["check"] == "consistency"
    assert r["checks"][1]["status"] == "not_measurable"

    ahead = make_user("user_b", goals=("tone", "rehab"), timeline="8_weeks", quiz_days_ago=14)
    for d in range(12):
        log(ahead, d)
    assert call("check_goal_achievement", user_id=ahead)["status"] == "ahead"

    behind = make_user("user_c", goals=("tone",), timeline="4_weeks", quiz_days_ago=20)
    log(behind, 1)
    r = call("check_goal_achievement", user_id=behind)
    assert r["status"] == "behind" and r["thresholds_used"]["ahead_if_ratio_at_least"] == 1.25
    assert "not from scientific or medical guidance" in r["note"]


def test_goal_check_weight_loss_and_strength_signals(test_db):
    gaining = make_user("user_d", goals=("weight_loss",), quiz_days_ago=25)
    for d in range(0, 24, 2):
        log(gaining, d)
    weigh(gaining, 20, 160.0)
    weigh(gaining, 0, 163.0)
    r = call("check_goal_achievement", user_id=gaining)
    assert r["status"] == "behind" and {"check": "weight_loss", "status": "behind"}.items() <= r["checks"][1].items()

    losing = make_user("user_e", goals=("weight_loss",), quiz_days_ago=25)
    for d in range(0, 24, 2):
        log(losing, d)
    weigh(losing, 20, 163.0)
    weigh(losing, 0, 160.0)
    assert call("check_goal_achievement", user_id=losing)["checks"][1]["status"] == "on_track"

    nodata = make_user("user_f", goals=("weight_loss",), quiz_days_ago=25)
    log(nodata, 0)
    assert call("check_goal_achievement", user_id=nodata)["checks"][1]["status"] == "not_enough_data"

    lifter = make_user("user_g", goals=("strength",), quiz_days_ago=25)
    for d in range(0, 24, 2):
        log(lifter, d, weight=40 if d >= 15 else 10)       # lifts got lighter recently
    r = call("check_goal_achievement", user_id=lifter)
    assert r["checks"][1]["check"] == "strength" and r["checks"][1]["status"] == "behind"

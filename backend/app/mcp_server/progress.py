"""get_progress_summary and check_goal_achievement (both read-only; neither writes anything).

Dates are calendar dates (YYYY-MM-DD); "today" is the server's UTC date unless a test passes one in.

check_goal_achievement also compares what was DONE against what was PLANNED: the workout days scheduled on the
user's calendar (calendar_entries, laid out from their generated plan) versus the ones they marked completed.
Marking a calendar day completed is what writes its workout_logs rows, so both checks read the same real data.
Calendar notes are never read here (they never reach the model; shared_rules.md rule 2).

IMPORTANT: the thresholds in check_goal_achievement are simple product heuristics so the Coach agent
has something concrete to react to. They are NOT scientific or medical guidance, and the result says so.
They are placeholders for the physical therapist to review (see THRESHOLDS below).
"""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from app.agents.context import agent_profile_for
from app.db import connect_readonly

WINDOW_DAYS = 30
REST_SUGGESTED_AFTER_DAYS = 10     # the Coach agent's overtraining flag: 10+ days in a row
WEIGHT_FLAT_LBS = 0.5              # body-weight changes smaller than this count as "flat"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _parse(d: str) -> date:
    return date.fromisoformat(d)


def _trend(first: float, latest: float, flat_below: float | None = None) -> dict:
    change = round(latest - first, 2)
    if flat_below is not None and abs(change) < flat_below:
        direction = "flat"
    else:
        direction = "flat" if change == 0 else ("up" if change > 0 else "down")
    return {"first": first, "latest": latest, "change": change, "direction": direction}


def _current_streak(days: set[date], today: date) -> int:
    """Consecutive days with a logged workout, counting back from today. If nothing is logged today yet,
    counting starts from yesterday, so an unfinished day doesn't wipe out a streak."""
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def get_progress_summary(user_id: int, today: date | None = None) -> dict:
    today = today or _today()
    start = today - timedelta(days=WINDOW_DAYS - 1)
    mid = today - timedelta(days=WINDOW_DAYS // 2 - 1)      # last 15 days start here
    conn = connect_readonly()
    try:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            return {"found": False, "message": "No such user."}
        logs = conn.execute(
            "SELECT date, sets, reps, weight_used FROM workout_logs WHERE user_id = ? AND date <= ? ORDER BY date",
            (user_id, today.isoformat())).fetchall()
        meas = conn.execute(
            "SELECT date, body_weight, measurements FROM measurements WHERE user_id = ? AND date BETWEEN ? AND ? "
            "ORDER BY date", (user_id, start.isoformat(), today.isoformat())).fetchall()
    finally:
        conn.close()

    all_days = {_parse(r["date"]) for r in logs}
    in_window = [r for r in logs if start <= _parse(r["date"]) <= today]
    window_days = {_parse(r["date"]) for r in in_window}

    def volume(rows) -> float:
        # sets x reps x weight, only for entries that have all three (bodyweight entries add no weight)
        return sum(r["sets"] * r["reps"] * r["weight_used"] for r in rows
                   if r["sets"] is not None and r["reps"] is not None and r["weight_used"] is not None)

    lifted = volume(in_window)
    streak = _current_streak(all_days, today)

    # measurement trends over the window
    weights = [(r["date"], r["body_weight"]) for r in meas if r["body_weight"] is not None]
    body_weight = {"entries": len(weights), "unit": "lb"}
    if len(weights) >= 2:
        body_weight.update(_trend(weights[0][1], weights[-1][1], WEIGHT_FLAT_LBS),
                           first_date=weights[0][0], latest_date=weights[-1][0])
    elif weights:
        body_weight.update(latest=weights[0][1], latest_date=weights[0][0])
    series: dict[str, list[tuple[str, float]]] = {}
    for r in meas:
        for key, value in json.loads(r["measurements"]).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                series.setdefault(key, []).append((r["date"], value))
    other = {k: {"entries": len(v), **(_trend(v[0][1], v[-1][1]) if len(v) >= 2 else {"latest": v[0][1]})}
             for k, v in sorted(series.items())}

    return {
        "found": True,
        "window": {"start": start.isoformat(), "end": today.isoformat(), "days": WINDOW_DAYS},
        "sessions_logged": len(window_days),
        "exercise_entries": len(in_window),
        "total_weight_lifted_lbs": round(lifted, 1),
        "weight_lifted_prior_15_days_lbs": round(volume([r for r in in_window if _parse(r["date"]) < mid]), 1),
        "weight_lifted_last_15_days_lbs": round(volume([r for r in in_window if _parse(r["date"]) >= mid]), 1),
        "current_streak_days": streak,
        "rest_day_suggested": streak >= REST_SUGGESTED_AFTER_DAYS,
        "last_workout_date": max(all_days).isoformat() if all_days else None,
        "body_weight_trend": body_weight,
        "other_measurement_trends": other,
        "definitions": {
            "session": "a calendar day with at least one logged workout entry",
            "total_weight_lifted_lbs": "sum of sets x reps x weight_used over the window; entries without a "
                                       "weight (bodyweight moves) add nothing",
            "current_streak_days": "consecutive days with a logged workout ending today (or yesterday, if "
                                   "nothing is logged yet today)",
            "rest_day_suggested": f"true when the streak is {REST_SUGGESTED_AFTER_DAYS} days or more",
        },
    }


# ---------------------------------------------------------------- goal check

# Simple, transparent product heuristics. Not science. PT TO REVIEW.
THRESHOLDS = {
    "target_sessions_per_week": 4,          # every plan has 4 training days a week (the 2026-10-25 rewrite)
    "ahead_if_ratio_at_least": 1.25,       # sessions per week / target
    "on_track_if_ratio_at_least": 0.75,
    "volume_ahead_if_ratio_at_least": 1.10,  # last 15 days vs the 15 days before (strength goal)
    "volume_on_track_if_ratio_at_least": 0.90,
    "min_days_since_quiz_to_judge": 7,
    "min_days_between_weigh_ins_to_judge": 7,
    "plan_on_track_if_completed_ratio_at_least": 0.75,   # completed / scheduled plan workout days so far
}
HEURISTIC_NOTE = ("These statuses come from simple app thresholds (listed in thresholds_used), not from scientific "
                  "or medical guidance. They have not been reviewed by a physical therapist. Do not present them "
                  "as science-backed.")


def _rate(ratio: float, ahead: float, on_track: float) -> str:
    return "ahead" if ratio >= ahead else "on_track" if ratio >= on_track else "behind"


def _plan_adherence(conn: sqlite3.Connection, user_id: int, start: date, today: date) -> dict:
    """Workout days the plan scheduled from `start` up to today, and how many were marked completed.
    Today only counts once it's done, so an unfinished today isn't a miss. Never reads notes."""
    row = conn.execute(
        "SELECT COUNT(*) AS scheduled, COALESCE(SUM(completed), 0) AS completed FROM calendar_entries "
        "WHERE user_id = ? AND day_type = 'workout' AND date >= ? AND (date < ? OR (date = ? AND completed = 1))",
        (user_id, start.isoformat(), today.isoformat(), today.isoformat())).fetchone()
    return {"plan_workouts_scheduled": row["scheduled"], "plan_workouts_completed": row["completed"]}


def check_goal_achievement(user_id: int, today: date | None = None) -> dict:
    today = today or _today()
    t = THRESHOLDS
    conn = connect_readonly()
    try:
        # Same PII boundary as get_user_profile: the goal only comes through agent_profile_for.
        profile = agent_profile_for(user_id, conn)
        quiz = conn.execute("SELECT created_at FROM quiz_profiles WHERE user_id = ?", (user_id,)).fetchone()
        started = datetime.fromisoformat(quiz["created_at"].replace("Z", "+00:00")).date() if quiz else None
        adherence = (_plan_adherence(conn, user_id, max(started, today - timedelta(days=WINDOW_DAYS - 1)), today)
                     if started else None)
    finally:
        conn.close()
    if profile is None or quiz is None or not profile.goal:
        return {"status": "insufficient_data", "reasons": ["No quiz profile with a goal yet."],
                "checks": [], "note": HEURISTIC_NOTE}

    summary = get_progress_summary(user_id, today)
    days_since_quiz = (today - started).days
    result = {
        "goal": profile.goal,
        "plan": {"days_since_quiz": days_since_quiz, "weeks_elapsed": round(days_since_quiz / 7, 1)},
        "progress": {**{k: summary[k] for k in ("sessions_logged", "total_weight_lifted_lbs",
                                                 "current_streak_days", "body_weight_trend")}, **adherence},
        "thresholds_used": t,
        "note": HEURISTIC_NOTE,
    }
    if days_since_quiz < t["min_days_since_quiz_to_judge"]:
        return {"status": "insufficient_data", "checks": [],
                "reasons": [f"The quiz was taken {days_since_quiz} day(s) ago; it's too early to judge "
                            f"(need {t['min_days_since_quiz_to_judge']}+ days)."], **result}

    checks = []
    # 1. Consistency applies to every goal. Judge over the time since the quiz if that's under 30 days.
    target = t["target_sessions_per_week"]
    weeks = min(WINDOW_DAYS, days_since_quiz) / 7
    per_week = summary["sessions_logged"] / weeks
    result["progress"].update(sessions_per_week=round(per_week, 2), weeks_considered=round(weeks, 1))
    ratio = per_week / target
    checks.append({"check": "consistency", "status": _rate(ratio, t["ahead_if_ratio_at_least"],
                                                             t["on_track_if_ratio_at_least"]),
                   "detail": f"{per_week:.1f} sessions per week vs the plan's {target}"})

    # 2. Goal-specific checks, only where the logs can actually measure the goal.
    for goal in [profile.goal]:
        if goal == "lose_weight":
            bw = summary["body_weight_trend"]
            if bw["entries"] >= 2 and (_parse(bw["latest_date"]) - _parse(bw["first_date"])).days >= \
                    t["min_days_between_weigh_ins_to_judge"]:
                status = "on_track" if bw["direction"] == "down" else "behind"
                checks.append({"check": "lose_weight", "status": status,
                               "detail": f"body weight {bw['direction']} ({bw['change']:+} lb over the window)"})
            else:
                checks.append({"check": "lose_weight", "status": "not_enough_data",
                               "detail": f"needs 2+ weigh-ins at least {t['min_days_between_weigh_ins_to_judge']} "
                                         "days apart"})
        elif goal == "stronger":
            prior, last = summary["weight_lifted_prior_15_days_lbs"], summary["weight_lifted_last_15_days_lbs"]
            if prior > 0:
                checks.append({"check": "stronger", "status": _rate(last / prior, t["volume_ahead_if_ratio_at_least"],
                                                                    t["volume_on_track_if_ratio_at_least"]),
                               "detail": f"{last:,.0f} lb lifted in the last 15 days vs {prior:,.0f} lb in the 15 before"})
            else:
                checks.append({"check": "stronger", "status": "not_enough_data",
                               "detail": "no weight logged in the earlier 15 days to compare with"})
        else:   # feel_good: nothing in the logs measures how someone feels
            checks.append({"check": goal, "status": "not_measurable",
                           "detail": "No logged measurement tracks feeling good, so it is judged on consistency only."})

    # 3. Did they do the plan they were given? Completed vs scheduled workout days on their calendar.
    scheduled, done = adherence["plan_workouts_scheduled"], adherence["plan_workouts_completed"]
    if scheduled:
        share = done / scheduled
        checks.append({"check": "plan_adherence",
                       "status": "on_track" if share >= t["plan_on_track_if_completed_ratio_at_least"] else "behind",
                       "detail": f"{done} of {scheduled} planned workout days marked done"})
    else:
        checks.append({"check": "plan_adherence", "status": "not_enough_data",
                       "detail": "no planned workout days on the calendar yet in this period"})

    judged = [c["status"] for c in checks if c["status"] in ("ahead", "on_track", "behind")]
    if "behind" in judged:
        status = "behind"
    elif all(s == "ahead" for s in judged):
        status = "ahead"
    else:
        status = "on_track"
    reasons = [f"{c['check']}: {c['status']} ({c['detail']})" for c in checks]
    return {"status": status, "reasons": reasons, "checks": checks, **result}

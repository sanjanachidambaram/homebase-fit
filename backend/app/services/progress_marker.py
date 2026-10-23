"""The progress marker at the top of the calendar: computed in code, worded by code templates. No AI.

Every number comes from a calculation that already exists; this module only reads them and adds them up:
  * goal status and plan adherence: app/mcp_server/progress.check_goal_achievement (the Coach's goal check)
  * calories: app.calendar.day_calories / strength_kcal (the Workout Reviewer's Compendium MET method) and each cardio
    log's estimate (app/services/cardio_estimate.py, same method)
  * pounds, only for a weight-loss goal: that calorie range / 3,500 (the Reviewer's rule of thumb and rounding),
    labelled as a rough approximation, never a promise
  * the fun fact: app/mcp_server/strength.compute_strength_equivalents on the pounds lifted in the last 30 days
The same "the model can't invent a number" rule as the Workout Reviewer (shared_rules.md rule 7) holds trivially:
there is no model here. Tone follows rule 5: warm, a little playful, never about bodies or food.
"""

import json
import random
from datetime import date, timedelta

from app.db import connect
from app.mcp_server.progress import check_goal_achievement, get_progress_summary
from app.mcp_server.strength import compute_strength_equivalents
from app.services.workout_review import CAVEAT_DIET, CAVEAT_POUNDS, KCAL_PER_POUND, POUNDS_ROUND_TO, _down, _up

CAVEATS_ANCHOR = "calorie-estimates"   # the one place on the calendar page with the full caveats
STATUS_LINES = {
    "ahead": "You're ahead of your plan this month. Look at you go!",
    "on_track": "You're on track with your plan. Steady wins this one.",
    "behind": "A few planned days slipped by. No stress: the next one is a fresh start.",
    "insufficient_data": "Your plan is just getting going, so there's not much to judge yet. Every day you log counts.",
}


def _lb(kcal: dict) -> dict:
    return {"low": _down(kcal["low"] / KCAL_PER_POUND, POUNDS_ROUND_TO),
            "high": _up(kcal["high"] / KCAL_PER_POUND, POUNDS_ROUND_TO)}


def _range_text(r: dict, unit: str) -> str:
    fmt = (lambda x: f"{x:g}") if unit == "lb" else (lambda x: f"{int(x):,}")
    if r["low"] == r["high"]:
        return f"{fmt(r['low'])} {unit}"
    if r["low"] == 0:                              # "0 to 0.2 lb" reads oddly; the range is the same
        return f"{fmt(r['high'])} {unit} or less"
    return f"{fmt(r['low'])} to {fmt(r['high'])} {unit}"


def build(uid: int, week_start: date, today: date) -> dict:
    from app import calendar as cal
    from app.cardio import cardio_logs_between
    from app.safety_rules import profile_needs_clinical_review

    if profile_needs_clinical_review(uid):
        return {"available": False, "reason": "No plan or calorie numbers while you're pregnant or postpartum."}
    week_end = week_start + timedelta(days=6)
    conn = connect()
    try:
        profile = conn.execute("SELECT goals FROM quiz_profiles WHERE user_id = ?", (uid,)).fetchone()
        rows = conn.execute("SELECT * FROM calendar_entries WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date",
                            (uid, week_start.isoformat(), week_end.isoformat())).fetchall()
        weight = cal._weight(conn, uid)
    finally:
        conn.close()
    if profile is None:
        return {"available": False, "reason": "Take the quiz to see your progress here."}
    goals = json.loads(profile["goals"])
    logs = cardio_logs_between(uid, week_start, week_end)

    # This week: what's done (calendar days + cardio logged on dates with no calendar day) and what's still planned.
    done_days = cal.day_calories(rows, logs, weight)
    entry_dates = {r["date"] for r in rows}
    loose = [l["estimate"]["kcal"] for l in logs if l["date"] not in entry_dates and l["estimate"].get("available")]
    kcal_done = {"low": sum(d["low"] for d in done_days.values()) + sum(k["low"] for k in loose),
                 "high": sum(d["high"] for d in done_days.values()) + sum(k["high"] for k in loose)}
    remaining = [r for r in rows if r["day_type"] == "workout" and not r["completed"] and r["date"] >= today.isoformat()]
    rest_kcal = [k for k in (cal.strength_kcal(json.loads(r["workout_content"]), weight) for r in remaining) if k]
    kcal_if_finished = {"low": kcal_done["low"] + sum(k["low"] for k in rest_kcal),
                        "high": kcal_done["high"] + sum(k["high"] for k in rest_kcal)}
    planned = [r for r in rows if r["day_type"] in ("workout", "cardio")]
    sessions_done = sum(1 for r in planned if r["completed"])
    cardio_minutes = sum(l["duration_minutes"] or 0 for l in logs)
    strength_minutes = sum(json.loads(r["workout_content"]).get("est_minutes") or 0
                           for r in rows if r["completed"] and r["day_type"] == "workout")

    goal = check_goal_achievement(uid, today)
    items = []
    if planned:
        items.append({"kind": "sessions", "value": {"done": sessions_done, "planned": len(planned)},
                      "text": f"{sessions_done} of {len(planned)} planned day{'s' if len(planned) != 1 else ''} "
                              f"done this week" + (". All of them!" if sessions_done == len(planned) else ".")})
    minutes = round(strength_minutes + cardio_minutes)
    if minutes:
        items.append({"kind": "minutes", "value": {"minutes": minutes},
                      "text": f"About {minutes} minutes of moving logged this week."})
    if kcal_done["high"]:
        items.append({"kind": "energy", "value": {"kcal": kcal_done}, "anchor": CAVEATS_ANCHOR,
                      "text": f"Your done days this week burned roughly {_range_text(kcal_done, 'kcal')} (an estimate)."})
    if "weight_loss" in goals and kcal_if_finished["high"]:
        lb = _lb(kcal_if_finished)
        finish = "If you finish this week's plan, your" if rest_kcal else "Your"
        items.append({"kind": "weight_change", "value": {"kcal": kcal_if_finished, "pounds": lb},
                      "anchor": CAVEATS_ANCHOR, "rough": True, "caveats": [CAVEAT_POUNDS, CAVEAT_DIET],
                      "text": f"{finish} workouts this week add up to roughly {_range_text(lb, 'lb')} of change, using "
                              f"the 3,500-calories-a-pound rule of thumb: a rough approximation, not a prediction."})
    lifted = get_progress_summary(uid, today)["total_weight_lifted_lbs"]
    if lifted:
        fact = compute_strength_equivalents(lifted, random.Random(f"{uid}-{week_start}"))   # same pick all week
        items.append({"kind": "fun_fact", "value": {"total_weight_lifted_lbs": lifted},
                      "text": f"In the last 30 days: {fact['headline']}" if fact.get("headline") else None,
                      "note": fact.get("note")})
    items = [i for i in items if i.get("text")]

    status = goal.get("status", "insufficient_data")
    return {"available": True, "week": {"start": week_start.isoformat(), "end": week_end.isoformat()},
            "goals": goals, "goal_status": status, "headline": STATUS_LINES.get(status, STATUS_LINES["insufficient_data"]),
            "items": items, "heuristic_note": goal.get("note"), "caveats_anchor": CAVEATS_ANCHOR,
            "computed_by": "code", "agent_called": False}

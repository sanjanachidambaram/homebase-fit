"""The Dashboard's "This week" card: how many workouts you've logged this week, and one playful fun fact about it.

Code only, no AI. The week runs Monday to Sunday (the calendar's weeks), up to today.

Workouts logged: the days this week with at least one logged workout or cardio session, the same "active day" the
streak counts (marking a calendar day done, or logging cardio, writes workout_logs rows; app/cardio.py).

The fun fact, from whatever was actually logged, in this order:
  1. Weight moved (sets x reps x weight): the Coach's own generator, app/mcp_server/strength.py
     compute_strength_equivalents (the highest tier reached, a random pick within it), phrased for the week.
  2. Distance (cardio logged as distance, or steps at a ballpark 2,000 steps per mile): Olympic track laps, football
     fields, Golden Gate Bridges.
  3. Time (cardio logged as minutes): soccer matches.
Tone (shared_rules.md rule 5): only objects and places; never the person's body, food or body weight. Every figure is a
ballpark for fun, and the card says so.
"""

import random
from datetime import date, timedelta

from app.db import connect_readonly
from app.mcp_server.strength import _count_text, compute_strength_equivalents

STEPS_PER_MILE = 2000        # a common ballpark (stride of about 2.6 ft)
DISTANCES = [                # smallest to largest; miles for ONE of the thing
    {"name": "football fields", "singular": "football field", "miles": 360 / 5280,
     "basis": "An American football field with end zones: 120 yards (360 ft)"},
    {"name": "Olympic track laps", "singular": "Olympic track lap", "miles": 400 / 1609.344,
     "basis": "One lap of a standard running track: 400 m"},
    {"name": "Golden Gate Bridges", "singular": "Golden Gate Bridge", "miles": 1.7,
     "basis": "The Golden Gate Bridge: about 1.7 miles long"},
]
SOCCER_MATCH_MINUTES = 90
NOTE = "Just for fun: ballpark comparisons, not measurements."


def week_bounds(today: date) -> tuple[date, date]:
    start = today - timedelta(days=today.weekday())
    return start, start + timedelta(days=6)


def _phrase(count: float, one: str, many: str) -> str:
    return f"about {_count_text(count)} {one if round(count, 1) == 1.0 else many}"


def distance_fact(miles: float, rng: random.Random, from_steps: bool = False) -> dict | None:
    if miles <= 0:
        return None
    reached = [d for d in DISTANCES if miles / d["miles"] >= 1]
    # Never the biggest thing every time: pick between the two largest it reaches, so a revisit can differ.
    d = rng.choice(reached[-2:]) if reached else DISTANCES[0]
    count = miles / d["miles"]
    steps_note = f", counting steps at {STEPS_PER_MILE:,} per mile" if from_steps else ""
    return {"kind": "distance", "text": f"This week you've covered {_phrase(count, d['singular'], d['name'])}!",
            "basis": f"{d['basis']}. You covered {round(miles, 2)} miles this week{steps_note}"}


def time_fact(minutes: int) -> dict | None:
    if minutes <= 0:
        return None
    count = minutes / SOCCER_MATCH_MINUTES
    text = (f"This week you've moved for {minutes} minutes: {_phrase(count, 'full soccer match', 'full soccer matches')}!"
            if count >= 1 else
            f"This week you've moved for {minutes} minutes: {round(count * 100)}% of a full soccer match. Keep going!")
    return {"kind": "time", "text": text, "basis": "A soccer match: 90 minutes of play"}


def weekly_summary(user_id: int, today: date, rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    start, end = week_bounds(today)
    span = (start.isoformat(), today.isoformat())
    conn = connect_readonly()
    try:
        days = conn.execute("SELECT COUNT(DISTINCT date) FROM workout_logs WHERE user_id = ? AND date BETWEEN ? AND ?",
                            (user_id, *span)).fetchone()[0]
        lifted = conn.execute(
            "SELECT COALESCE(SUM(sets * reps * weight_used), 0) FROM workout_logs WHERE user_id = ? "
            "AND date BETWEEN ? AND ? AND sets IS NOT NULL AND reps IS NOT NULL AND weight_used IS NOT NULL",
            (user_id, *span)).fetchone()[0]
        cardio = conn.execute(
            "SELECT COALESCE(SUM(steps), 0) AS steps, COALESCE(SUM(distance_miles), 0) AS miles, "
            "COALESCE(SUM(duration_minutes), 0) AS minutes FROM cardio_logs WHERE user_id = ? AND date BETWEEN ? AND ?",
            (user_id, *span)).fetchone()
    finally:
        conn.close()
    lifted = float(lifted)
    miles = float(cardio["miles"]) + cardio["steps"] / STEPS_PER_MILE
    minutes = int(cardio["minutes"])

    fact = None
    if lifted > 0:
        eq = compute_strength_equivalents(lifted, rng)
        pick = next(c for c in eq["comparisons"] if c["name"] == eq["headline_comparison"])
        fact = {"kind": "lifted",
                "text": (f"This week you've lifted {pick['phrase']}!" if pick["count"] >= 1 else
                         f"This week you've lifted {pick['count_text']} of a chihuahua. Keep going!"),
                "basis": f"{pick['basis']}. You moved {round(lifted):,} lb this week (sets x reps x weight)"}
    if fact is None:
        fact = distance_fact(miles, rng, from_steps=bool(cardio["steps"]))
    if fact is None:
        fact = time_fact(minutes)
    return {
        "week_start": start.isoformat(), "week_end": end.isoformat(),
        "workouts_logged": days,
        "weight_lifted_lbs": round(lifted, 1), "cardio_miles": round(miles, 2), "cardio_minutes": minutes,
        "fun_fact": fact,
        "note": NOTE if fact else "Log a workout or some cardio this week to unlock a fun fact.",
    }

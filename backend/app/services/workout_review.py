"""Workout review, computed entirely in code (no LLM). The Workout Reviewer agent only narrates this result.

1. Coverage: which of the 4 workout groups the plans are built from (Cardio, Upper body, Lower body, Mobility + core;
   since 2026-10-25) a session includes, a suggestion naming the ones it doesn't, and push/pull balance in the
   upper body (exercises.force: push | pull | static | unclassified).
2. Outcome estimate, always as a wide range, never a single number:
   - Energy per session from MET values in the 2024 Adult Compendium of Physical Activities (Herrmann et al.,
     J Sport Health Sci 2024;13(1):6-12). The Compendium defines 1 MET as about 1.0 kcal per kg per hour, so
     kcal = MET x body weight (kg) x hours. Low end: code 02054, resistance training, multiple exercises, 8-15
     reps (3.5 METs). High end: code 02020, vigorous calisthenics such as push-ups and burpees (7.5 METs; 02040,
     vigorous circuit training with minimal rest, is also 7.5). Where someone lands depends on how hard they work.
   - Weekly: per session x the plan's training days (always 4 since the 2026-10-25 rewrite).
   - Pounds, only for people whose goal is losing weight: weekly kcal x 4 weeks / 3,500, labelled as the rough,
     long-used approximation it is.
   Weight is asked only on the losing-weight path, so other goals get no calorie numbers (no weight to use).
   Ranges are rounded outward (low down, high up) so they never look more precise than they are.
"""

import json
import math
import re
import sqlite3
from collections import Counter

from app.db import connect_readonly

# The 4 workout groups every plan is built from (app/services/program_generator.py), in display order.
WORKOUT_GROUPS = ("cardio", "upper", "lower", "mobility_core")
GROUP_LABELS = {"cardio": "Cardio", "upper": "Upper body", "lower": "Lower body", "mobility_core": "Mobility + core"}
# How each group is named inside a sentence ("doesn't include any cardio, lower-body, or mobility/core work").
GROUP_WORDS = {"cardio": "cardio", "upper": "upper-body", "lower": "lower-body", "mobility_core": "mobility/core"}
UPPER_BODY = ("chest", "shoulders", "arms", "back")
# Library moves that are cardio by name although the library files them under full_body with no category.
CARDIO_NAME = re.compile(r"jumping jack|march|step jack|high knee|mountain climber|burpee|jog|run|skip|rope", re.I)
# Mobility and core staples the library files under back or core (e.g. Bird Dog is a "back" move).
MOBILITY_NAME = re.compile(r"bird dog|cat.?cow|superman|dead bug|plank|pelvic tilt|hip circle", re.I)

COMPENDIUM_SOURCE = "compendium-physical-activities"
CDC_SOURCE = "cdc-losing-weight"
MET_LOW = {"met": 3.5, "code": "02054",
           "activity": "Resistance (weight) training, multiple exercises, 8-15 reps at varied resistance"}
MET_HIGH = {"met": 7.5, "code": "02020",
            "activity": "Calisthenics (e.g., pushups, sit ups, pull-ups, jumping jacks, burpees), vigorous effort"}
KCAL_PER_KG_HOUR_PER_MET = 1.0          # Compendium: 1 MET is about 1.0 kcal/kg/h
LB_TO_KG = 0.45359237
KCAL_PER_POUND = 3500                  # the old rule of thumb; labelled as an approximation wherever it's used
WEEKS_SHOWN = 4                        # the pound estimate covers the next 4 weeks
PLAN_DAYS_PER_WEEK = 4                 # every plan has 4 training days (app/services/program_generator.py)

KCAL_ROUND_TO = 5
POUNDS_ROUND_TO = 0.1

CAVEAT_COMPENDIUM = ("These are estimates from average MET values in the 2024 Adult Compendium of Physical "
                     "Activities, which itself says its values don't reflect precise individual energy use.")
CAVEAT_EFFORT = ("Where you land depends on how hard you work: steady sets with full rests sit near the low end, "
                 "vigorous work with little rest near the high end.")
CAVEAT_POUNDS = ("The pound figures use the 3,500-calories-per-pound rule of thumb: a rough, long-used approximation, "
                 "not a precise prediction.")
CAVEAT_DIET = ("They count only the workout. Exercise on its own is usually a small piece of weight change compared "
               "with eating habits; sleep and stress play a part too.")
CDC_PACE = ("For context, the CDC notes that people who lose weight at a gradual, steady pace of about 1 to 2 pounds "
            "a week are more likely to keep it off.")


def _down(x: float, step: float) -> float:
    return round(math.floor(x / step + 1e-9) * step, 1)


def _up(x: float, step: float) -> float:
    return round(math.ceil(x / step - 1e-9) * step, 1)


def _int(x: float) -> int | float:
    return int(x) if float(x).is_integer() else x


# ---------------------------------------------------------------- 1. coverage

def workout_groups(e: dict) -> tuple[str, ...]:
    """Which of the 4 workout groups a library exercise counts toward, from its database fields.
    Full-body strength moves (e.g. a squat to press) count toward both upper and lower body."""
    name, group, category = e["name"], e["muscle_group"], e.get("category")
    if category == "cardio" or (group == "full_body" and CARDIO_NAME.search(name)):
        return ("cardio",)
    if category == "stretching" or group == "core" or MOBILITY_NAME.search(name):
        return ("mobility_core",)
    if group in UPPER_BODY:
        return ("upper",)
    if group == "legs":
        return ("lower",)
    return ("upper", "lower")                    # full_body strength / lifting moves


def _either(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + (", or " if len(words) > 2 else " or ") + words[-1]


def suggestion_for(missing: list[str]) -> str | None:
    """The coverage suggestion, written by code: it names exactly the groups the session doesn't include."""
    if not missing:
        return None
    words = [GROUP_WORDS[g] for g in missing]
    return (f"This session doesn't include any {_either(words)} work. Consider adding "
            f"{'some' if len(missing) == 1 else 'one of those'} next time.")


def coverage(exercises: list[dict]) -> dict:
    """exercises: [{exercise_id, name, muscle_group, category, force}] (all from the database)."""
    groups = [workout_groups(e) for e in exercises]
    counts = Counter(g for gs in groups for g in gs)
    hit = [{"group": g, "label": GROUP_LABELS[g], "exercises": counts[g]} for g in WORKOUT_GROUPS if counts[g]]
    missing = [g for g in WORKOUT_GROUPS if not counts[g]]

    upper = [e for e, gs in zip(exercises, groups) if gs == ("upper",)]
    f = Counter(e.get("force") or "unclassified" for e in upper)
    push, pull = f["push"], f["pull"]
    if not upper:
        balance = "No upper-body exercises, so there's no push/pull balance to check."
    elif push == pull == 0:
        balance = "The upper-body work is all holds or moves with no single direction, so it's neither pushing nor pulling."
    elif pull == 0:
        balance = f"No pull exercises: the upper-body work is all pushing ({push} push)."
    elif push == 0:
        balance = f"No push exercises: the upper-body work is all pulling ({pull} pull)."
    elif max(push, pull) >= 2 * min(push, pull):
        balance = f"Mostly {'pushing' if push > pull else 'pulling'} ({push} push, {pull} pull)."
    else:
        balance = f"Pushing and pulling are roughly balanced ({push} push, {pull} pull)."

    notes = []
    both = sum(1 for gs in groups if len(gs) > 1)
    if both:
        notes.append(f"{both} full-body strength move{'s' if both > 1 else ''} {'are' if both > 1 else 'is'} counted "
                     "toward both upper and lower body.")
    return {
        "groups_hit": hit,
        "groups_missing": missing,
        "suggestion": suggestion_for(missing),
        "upper_body_balance": {"push": push, "pull": pull, "static": f["static"],
                               "unclassified": f["unclassified"], "note": balance},
        "notes": notes,
    }


# ---------------------------------------------------------------- 2. outcome estimate

NO_WEIGHT_REASON = ("We only ask for your weight when your goal is losing weight, so there's no calorie estimate "
                    "for your plan.")


def estimate(minutes: float, weight_lb: float | None, days_per_week: int | None, goal: str | None) -> dict:
    if not weight_lb:
        return {"available": False, "reason": NO_WEIGHT_REASON}
    kg, hours = weight_lb * LB_TO_KG, minutes / 60
    low = _int(_down(MET_LOW["met"] * KCAL_PER_KG_HOUR_PER_MET * kg * hours, KCAL_ROUND_TO))
    high = _int(_up(MET_HIGH["met"] * KCAL_PER_KG_HOUR_PER_MET * kg * hours, KCAL_ROUND_TO))
    out = {
        "available": True,
        "session_minutes": round(minutes),
        "per_session_kcal": {"low": low, "high": high},
        "sessions_per_week": days_per_week,
        "weekly_kcal": None,
        "weight_change": None,
        "method": {
            "formula": "kcal = MET x body weight (kg) x hours, using about 1 kcal per kg per hour per MET",
            "low": MET_LOW, "high": MET_HIGH,
        },
        "caveats": [CAVEAT_COMPENDIUM, CAVEAT_EFFORT],
        "sources": [COMPENDIUM_SOURCE],
    }
    if days_per_week:
        out["weekly_kcal"] = {"low": low * days_per_week, "high": high * days_per_week}
    if days_per_week and goal == "lose_weight":
        weeks = WEEKS_SHOWN
        w = out["weekly_kcal"]
        out["weight_change"] = {
            "weeks": weeks,
            "pounds": {"low": _down(w["low"] * weeks / KCAL_PER_POUND, POUNDS_ROUND_TO),
                       "high": _up(w["high"] * weeks / KCAL_PER_POUND, POUNDS_ROUND_TO)},
            "label": "A rough, long-used approximation (3,500 calories per pound), not a precise prediction.",
            "cdc_context": CDC_PACE,
        }
        out["caveats"] += [CAVEAT_POUNDS, CAVEAT_DIET]
        out["sources"].append(CDC_SOURCE)
    return out


# ---------------------------------------------------------------- putting it together

def _citations(conn: sqlite3.Connection, ids: list[str]) -> list[dict]:
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT id, name, url FROM sources WHERE id IN ({','.join('?' for _ in ids)})", ids)}
    return [rows[i] for i in ids if i in rows]


def review(user_id: int, items: list[dict]) -> dict:
    """items: [{exercise_id, est_minutes}]. Names, muscle groups and directions come from the database, never
    from the client; the profile fields used for the math are read here and never sent to the model."""
    conn = connect_readonly()
    try:
        ids = [i["exercise_id"] for i in items]
        db = {r["id"]: dict(r) for r in conn.execute(
            f"SELECT id, name, muscle_group, category, force FROM exercises WHERE id IN ({','.join('?' for _ in ids)})",
            ids)}
        profile = conn.execute(
            "SELECT weight, goal FROM quiz_profiles WHERE user_id = ?", (user_id,)).fetchone()
        exercises = [{"exercise_id": i, **{k: db[i][k] for k in ("name", "muscle_group", "category", "force")}}
                     for i in ids if i in db]
        minutes = sum(float(i["est_minutes"]) for i in items if i["exercise_id"] in db)
        est = estimate(minutes, profile["weight"] if profile else None, PLAN_DAYS_PER_WEEK if profile else None,
                       profile["goal"] if profile else None)
        citations = _citations(conn, est.get("sources", []))
    finally:
        conn.close()
    cov = coverage(exercises)
    return {"exercises": [{k: e[k] for k in ("name", "muscle_group", "force")} | {"workout_groups": list(workout_groups(e))}
                          for e in exercises],
            "coverage": cov, "estimate": est, "citations": citations}

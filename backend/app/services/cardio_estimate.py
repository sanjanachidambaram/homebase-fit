"""Calories for a cardio log, computed in code (no AI). Same method as the Workout Reviewer (workout_review.py):
kcal = MET x body weight (kg) x hours, with MET values from the 2024 Adult Compendium of Physical Activities
(1 MET is about 1 kcal per kg per hour), always a range rounded outward, never a single number.

Each activity type has a low and a high Compendium code (an easier and a harder way of doing it). How it was measured:
  * minutes: low MET x kg x hours  to  high MET x kg x hours.
  * distance (walking, running, cycling): the Compendium codes that state a speed give calories per mile
    (MET x kg / mph); the range is the lowest to highest of those across the listed codes and their speed ranges.
  * steps (walking and hiking only): a rough rule of thumb of about 2,000 to 2,500 steps per mile, depending on
    stride, turns steps into a distance range, then the walking per-mile range applies. Labelled as rough.
"Other" has no Compendium code we can honestly pick, so it gets no estimate. Pregnant / postpartum users get no
estimate at all (shared_rules.md rule 9).

Codes checked against pacompendium.com (2024 Adult Compendium) on 2026-10-23.
"""

from app.services.workout_review import (CAVEAT_COMPENDIUM, COMPENDIUM_SOURCE, KCAL_PER_KG_HOUR_PER_MET, KCAL_ROUND_TO,
                                         LB_TO_KG, _down, _int, _up)


def _c(code: str, met: float, activity: str, mph: tuple[float, float] | None = None) -> dict:
    return {"code": code, "met": met, "activity": activity, **({"mph": mph} if mph else {})}


# type -> label, the low and high codes for minutes, and (walking/running/cycling) the codes that state a speed.
CARDIO_TYPES: dict[str, dict] = {
    "walking": {"label": "Walking", "steps": True,
                "low": _c("17170", 3.0, "Walking, 2.5 mph, firm, level surface", (2.5, 2.5)),
                "high": _c("17220", 5.5, "Walking, 4.0 to 4.4 mph, level, firm surface, very brisk pace", (4.0, 4.4)),
                "speed_codes": [_c("17170", 3.0, "Walking, 2.5 mph", (2.5, 2.5)),
                                _c("17190", 3.8, "Walking, 2.8 to 3.4 mph, moderate pace", (2.8, 3.4)),
                                _c("17200", 4.8, "Walking, 3.5 to 3.9 mph, brisk", (3.5, 3.9)),
                                _c("17220", 5.5, "Walking, 4.0 to 4.4 mph, very brisk", (4.0, 4.4))]},
    "hiking": {"label": "Hiking or trail walking", "steps": True,
               "low": _c("17081", 3.8, "Hiking slowly or ambling through fields and hillsides, no load"),
               "high": _c("17080", 6.0, "Hiking, cross country")},
    "running": {"label": "Running or jogging",
                "low": _c("12028", 6.5, "Running, 4.0 to 4.2 mph (13-minute mile)", (4.0, 4.2)),
                "high": _c("12090", 12.0, "Running, 8 mph (7.5-minute mile)", (8.0, 8.0)),
                "speed_codes": [_c("12028", 6.5, "Running, 4.0 to 4.2 mph", (4.0, 4.2)),
                                _c("12030", 8.5, "Running, 5.0 to 5.2 mph", (5.0, 5.2)),
                                _c("12050", 9.3, "Running, 6.0 to 6.3 mph", (6.0, 6.3)),
                                _c("12070", 11.0, "Running, 7 mph", (7.0, 7.0)),
                                _c("12090", 12.0, "Running, 8 mph", (8.0, 8.0))]},
    "cycling": {"label": "Cycling (outdoors)",
                "low": _c("01010", 4.0, "Bicycling, <10 mph, leisure, to work or for pleasure"),
                "high": _c("01040", 10.0, "Bicycling, 14-15.9 mph, racing or leisure, fast, vigorous effort", (14.0, 15.9)),
                "speed_codes": [_c("01018", 3.5, "Bicycling, leisure 5.5 mph", (5.5, 5.5)),
                                _c("01019", 5.8, "Bicycling, leisure, 9.4 mph", (9.4, 9.4)),
                                _c("01020", 6.8, "Bicycling, 10-11.9 mph, light effort", (10.0, 11.9)),
                                _c("01030", 8.0, "Bicycling, 12-13.9 mph, moderate effort", (12.0, 13.9)),
                                _c("01040", 10.0, "Bicycling, 14-15.9 mph, vigorous effort", (14.0, 15.9))]},
    "stationary_bike": {"label": "Stationary bike",
                        "low": _c("01214", 4.0, "Bicycling, stationary, 50 watts, light effort"),
                        "high": _c("01228", 8.0, "Bicycling, stationary, 126-150 watts")},
    "elliptical": {"label": "Elliptical",
                   "low": _c("02048", 5.0, "Elliptical trainer, moderate effort"),
                   "high": _c("02049", 9.0, "Elliptical trainer, vigorous effort")},
    "rowing": {"label": "Rowing machine",
               "low": _c("02071", 5.0, "Rowing, stationary ergometer, general, <100 watts, moderate effort"),
               "high": _c("02072", 7.5, "Rowing, stationary, 100 to 149 watts, vigorous effort")},
    "stairs": {"label": "Stair climbing or stair machine",
               "low": _c("17133", 4.5, "Stair climbing, slow pace"),
               "high": _c("02065", 9.3, "Stair treadmill ergometer, general")},
    "jump_rope": {"label": "Jump rope",
                  "low": _c("02069", 9.0, "Jumping rope, Digi-Jump Machine, 120 jumps/minute"),
                  "high": _c("02068", 11.0, "Rope skipping exercise, general")},
    "dance": {"label": "Dance cardio",
              "low": _c("02005", 4.8, "Aerobic dance, low impact, moderate effort"),
              "high": _c("02006", 8.0, "Aerobic dance, high impact, vigorous effort")},
    "swimming": {"label": "Swimming",
                 "low": _c("18255", 4.8, "Swimming, backstroke, recreational"),
                 "high": _c("18230", 9.8, "Swimming laps, freestyle, fast, vigorous effort")},
    "other": {"label": "Something else"},   # no estimate: we won't guess a MET value
}
DISTANCE_TYPES = {t for t, v in CARDIO_TYPES.items() if v.get("speed_codes")}
STEP_TYPES = {t for t, v in CARDIO_TYPES.items() if v.get("steps")}

# The library's cardio exercises (free-exercise-db category "cardio") and the type each one is.
LIBRARY_TYPES = {
    "Bicycling": "cycling", "Bicycling_Stationary": "stationary_bike", "Recumbent_Bike": "stationary_bike",
    "Elliptical_Trainer": "elliptical", "Jogging_Treadmill": "running", "Running_Treadmill": "running",
    "Walking_Treadmill": "walking", "Trail_Running_Walking": "hiking", "Rowing_Stationary": "rowing",
    "Stairmaster": "stairs", "Step_Mill": "stairs", "Rope_Jumping": "jump_rope",
    "Prowler_Sprint": "other", "Skating": "other",
}

STEPS_PER_MILE = (2000, 2500)   # rough rule of thumb; stride length varies
KM_PER_MILE = 1.609344
STEPS_LABEL = ("Steps are turned into distance with a rough rule of thumb (about 2,000 to 2,500 steps a mile, "
               "depending on your stride), so this one is extra rough.")
NO_ESTIMATE = {"other": "We don't have a fair calorie number for this activity, so we don't guess one."}


def _range(low: float, high: float) -> dict:
    return {"low": _int(_down(low, KCAL_ROUND_TO)), "high": _int(_up(high, KCAL_ROUND_TO))}


def _per_mile(codes: list[dict]) -> tuple[float, float]:
    """kcal per mile per kg: MET / mph, over every listed code and both ends of its speed range."""
    values = [c["met"] / mph for c in codes for mph in c["mph"]]
    return min(values), max(values)


def estimate_cardio(cardio_type: str | None, *, minutes: float | None = None, steps: int | None = None,
                    miles: float | None = None, weight_lb: float | None) -> dict:
    t = CARDIO_TYPES.get(cardio_type or "")
    if t is None or "low" not in t:
        return {"available": False, "reason": NO_ESTIMATE["other"]}
    if not weight_lb:
        return {"available": False,
                "reason": "Add your weight in the quiz to see a calorie estimate (it's only used for this math)."}
    kg = weight_lb * LB_TO_KG
    out = {"available": True, "method": {"formula": "kcal = MET x body weight (kg) x hours, using about 1 kcal per "
                                                    "kg per hour per MET", "low": t["low"], "high": t["high"]},
           "caveats": [CAVEAT_COMPENDIUM], "sources": [COMPENDIUM_SOURCE], "rough": False}
    k = KCAL_PER_KG_HOUR_PER_MET
    if minutes:
        hours = minutes / 60
        out["kcal"] = _range(t["low"]["met"] * k * kg * hours, t["high"]["met"] * k * kg * hours)
        out["basis"] = f"{_int(round(minutes))} min of {t['label'].lower()}"
        return out
    if steps:
        if cardio_type not in STEP_TYPES:
            return {"available": False, "reason": "Step counts work for walking and hiking."}
        lo, hi = _per_mile(CARDIO_TYPES["walking"]["speed_codes"])
        miles_low, miles_high = steps / STEPS_PER_MILE[1], steps / STEPS_PER_MILE[0]
        out.update(kcal=_range(lo * k * kg * miles_low, hi * k * kg * miles_high), rough=True,
                   basis=f"{steps:,} steps (about {miles_low:.1f} to {miles_high:.1f} miles)")
        out["method"] = {**out["method"], "steps_per_mile": STEPS_PER_MILE,
                         "per_mile_codes": CARDIO_TYPES["walking"]["speed_codes"]}
        out["caveats"].append(STEPS_LABEL)
        return out
    if miles:
        if cardio_type not in DISTANCE_TYPES:
            return {"available": False, "reason": "Distance works for walking, running and cycling."}
        lo, hi = _per_mile(t["speed_codes"])
        out.update(kcal=_range(lo * k * kg * miles, hi * k * kg * miles), basis=f"{miles:g} miles")
        out["method"] = {**out["method"], "per_mile_codes": t["speed_codes"]}
        return out
    return {"available": False, "reason": "Add minutes, steps or a distance to see an estimate."}


def types_for_api() -> list[dict]:
    return [{"value": k, "label": v["label"], "distance": k in DISTANCE_TYPES, "steps": k in STEP_TYPES,
             "estimate": "low" in v} for k, v in CARDIO_TYPES.items()]

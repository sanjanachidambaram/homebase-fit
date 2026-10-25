"""Deterministic plan generator. Plain Python: there is NO LLM call anywhere in this module.

Input: the user's quiz profile (one goal, experience level, equipment, injury flags). Output: a WeeklyProgram for a
6-month plan (PLAN_WEEKS = 26 weeks, decided 2026-10-25): the goal's repeating block of weeks (2, 4 or 8) is the
pattern for all 26, and the weights climb across all 26 by the goal's rule. Only the pattern is stored; any date's
day and weights are worked out from it (app/calendar.py: plan_day_on, weight_suggestions). Rules:
backend/prompts/shared_rules.md, rules 6 and 8. Rewritten 2026-10-25.

  1. Safety first. Pregnant / postpartum -> no plan (needs OB-GYN-reviewed guidance first). Any injury flag ->
     checked_only for every exercise search (app/safety_rules.py), no exceptions. Every candidate comes from the
     same tested SQL filter the MCP tool uses (app.mcp_server.search), so injury filtering applies on top of
     whichever goal is picked, unchanged.
  2. The goal fixes the week: always 4 training days, as categories (Upper body, Lower body, Mobility + core,
     Cardio), and how the weeks repeat:
        Getting stronger   3 strength days (each Upper OR Lower, never mixed) + 1 cardio; a 2-week block, so the same
                           exercises come back on odd weeks and on even weeks (week 1 = 3 = 5...).
        Losing weight      2 strength days (Upper, Lower) + 2 cardio; a 4-week block: weeks 1-4 each different,
                           weeks 5-8 repeat them, and so on.
        Feeling good       2 mobility/core days + 1 strength day + 1 cardio; an 8-week block (weeks 9-16 repeat 1-8).
  3. Cardio days prescribe nothing: they read "Cardio of your choice" and the person logs whatever they did
     (app/cardio.py, with a code-only Compendium calorie estimate). No cardio exercise is ever picked from the library.
     Strength and mobility days are filled from slots. A strength day always hits at least two different muscle
     groups in its category (Upper: a push and a pull; Lower: a knee-dominant and a hip-dominant move) plus at
     least two accessories. Each slot prefers a short "backbone" list of effective, easy-at-home moves (push-ups, rows, squats, glute bridges,
     planks...) matched against the real library, never invented, and rotates through the pool so each day in the
     block gets different exercises where the pool allows.
  4. Sets, reps, rest and session length come from the goal_protocols row (goal x experience level).
  5. Weights: default starting weights by experience level (beginner: bodyweight only, so no number; intermediate
     10 lb arms / 20 lb legs; advanced 20 / 40), always shown as editable suggestions. Week 1 is a calibration week;
     after that suggestions build on what the person actually logged (app/calendar.py) and go up by the goal's rule
     (weight_steps / suggested_weight below).
Same profile in, same plan out.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from app.content import REVIEW_NOTICE
from app.db import connect_readonly
from app.mcp_server.search import contraindicated_exercises, search_all_exercises
from app.safety_rules import checked_only_for, needs_clinical_review

GOALS = ("stronger", "lose_weight", "feel_good")
GOAL_LABELS = {"stronger": "Getting stronger", "lose_weight": "Losing weight",
               "feel_good": "Just feeling good in my body"}
EXPERIENCE = ("beginner", "intermediate", "advanced")
WEEK = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
Category = Literal["upper", "lower", "mobility", "cardio"]
CATEGORY_LABELS = {"upper": "Upper body", "lower": "Lower body", "mobility": "Mobility + core",
                   "cardio": "Cardio of your choice"}
STRENGTH = ("upper", "lower")

# The week by goal: for each week of the repeating block, weekday -> category. Always 4 training days, on Monday,
# Wednesday, Friday and Saturday for every goal, so there's a rest day between most of them.
STRUCTURES: dict[str, list[dict[str, str]]] = {
    "stronger": [{"mon": "upper", "wed": "lower", "fri": "upper", "sat": "cardio"},
                 {"mon": "lower", "wed": "upper", "fri": "lower", "sat": "cardio"}],
    "lose_weight": [{"mon": "upper", "wed": "cardio", "fri": "lower", "sat": "cardio"}] * 4,
    "feel_good": [{"mon": "mobility", "wed": "upper" if i % 2 == 0 else "lower", "fri": "mobility", "sat": "cardio"}
                  for i in range(8)],
}
BLOCK_WEEKS = {g: len(s) for g, s in STRUCTURES.items()}   # 2, 4, 8
TRAINING_DAYS = 4
# Every plan runs 6 months: 26 weeks (182 days) from the day the quiz is saved, the goal's block repeating throughout.
PLAN_WEEKS = 26
PLAN_DAYS = PLAN_WEEKS * 7

# ---------------------------------------------------------------- weights (shared_rules.md rule 8)
WEIGHTED_EQUIPMENT = {"dumbbells", "kettlebells", "barbell", "ez_curl_bar", "cable", "machine", "medicine_ball"}
DEFAULT_WEIGHT_LB = {"beginner": None, "intermediate": {"arms": 10, "legs": 20}, "advanced": {"arms": 20, "legs": 40}}
WEIGHT_STEP_LB = {"stronger": {"arms": 2.5, "legs": 5}, "lose_weight": {"arms": 5, "legs": 5},
                  "feel_good": {"arms": 0, "legs": 0}}
LOSE_WEIGHT_STEP_WEEKS = 4
WEIGHT_RULES = {
    "stronger": "The weight goes up each time a day repeats: +2.5 lb for arm exercises and +5 lb for leg exercises. "
                "How many reps you do is your call (going to failure is your judgment during the set, not "
                "something the app works out).",
    "lose_weight": "Weights go up 5 lb every 4 weeks, when the 4-week pattern starts again.",
    "feel_good": "Weights stay wherever you set them. There are no automatic increases.",
}
CALIBRATION_NOTE = ("Week 1 is a calibration week: the weights shown are only starting suggestions, so log what you "
                    "actually did. From week 2, suggestions build on your week 1 numbers. You can change any weight "
                    "any time.")

# ---------------------------------------------------------------- picking
HOUSEHOLD = ("none", "chair")   # bodyweight moves and a sturdy chair are assumed available at home
QUIZ_EQUIPMENT = {"bodyweight": ["none"], "dumbbells": ["dumbbells"], "kettlebells": ["kettlebells"],
                  "resistance_band": ["resistance_band"], "mat": ["mat"]}
DIFFICULTY_ALLOWED = {"beginner": {"beginner"}, "intermediate": {"beginner", "intermediate"},
                      "advanced": {"beginner", "intermediate", "advanced"}}
NEVER_IN_STRENGTH = {"olympic weightlifting", "strongman", "powerlifting", "stretching", "cardio", "plyometrics"}
# Jumping and landing moves, and explosive lifts (cleans, snatches, jerks, thrusters: a fast loaded knee dip), are left
# out of low-impact plans (beginners, or anyone with an injury flag).
HIGH_IMPACT = re.compile(r"jump|burpee|\bhop|bound|skater|plyo|tuck|sprint|\bclean\b|snatch|\bjerk|thruster", re.I)
# Near-duplicate moves: at most one of each family on a day (no day of three calf raises).
ONE_PER_DAY = (re.compile(r"calf raise", re.I), re.compile(r"bridge|butt lift|hip thrust", re.I))
HOLD = re.compile(r"\b(plank|hold|wall sit|bridge hold|superman)\b", re.I)
# Moves that need a pull-up bar or something to hang from: only with a full gym (nobody said they have a bar).
NEEDS_BAR = re.compile(r"pull-?ups?\b|chin-?ups?\b|muscle.?up|inverted row|hanging", re.I)
CLINICAL_REVIEW_MESSAGE = (
    "Because you're pregnant or postpartum, we're not generating a plan yet. Exercise during and after "
    "pregnancy needs guidance from a clinician, and ours is still waiting on review by an OB-GYN. Please talk "
    "with your OB-GYN or midwife about what's right for you."
)
MOBILITY_HOLD = "20-30s hold"
MOBILITY_REST = 15


LEG_ACCESSORY = r"lunge|step.?up|calf|squat|bridge|thrust|abduct|adduct|kickback|side.?lying|deadlift|leg curl|wall sit"


@dataclass(frozen=True)
class Slot:
    name: str
    groups: tuple[str, ...]                   # library muscle groups this slot draws from
    backbone: tuple[str, ...] = ()            # name patterns, in priority order: the "most effective at home" list
    match: str | None = None                  # the slot's movement (name or primary muscles); None = any in groups
    accessory: bool = False
    stretch_ok: bool = False                  # mobility slots may use stretches


SLOTS: dict[str, list[Slot]] = {
    # Upper: a push (chest) and a pull (back) = two muscle groups, then accessories for shoulders and arms.
    "upper": [Slot("push", ("chest",), (r"push-?up", r"\bpress\b"), r"push-?up|press|fly|flye|dip"),
              Slot("pull", ("back",), (r"\brow\b", r"pull.?apart"), r"row|pull|fly|flye|face"),
              Slot("shoulders", ("shoulders",), (r"overhead press|shoulder press|military press", r"pull.?apart",
                                                 r"raise"), None, accessory=True),
              Slot("arms", ("arms",), (r"\bcurl", r"\bdips?\b|triceps"), None, accessory=True)],
    # Lower: knee-dominant (quads) and hip-dominant (glutes / hamstrings) = two muscle groups, then accessories.
    "lower": [Slot("knee", ("legs",), (r"squat", r"lunge", r"step.?up"), r"squat|lunge|step.?up|split|quadriceps"),
              Slot("hip", ("legs",), (r"glute bridge|butt lift|hip thrust", r"romanian|stiff.?leg"),
                   r"bridge|thrust|deadlift|good morning|glutes|hamstrings"),
              Slot("legs accessory", ("legs",), (r"lunge", r"step.?up", r"calf raise"), LEG_ACCESSORY, accessory=True),
              Slot("legs accessory", ("legs",), (r"calf raise", r"side.?lying|abduct|adduct"), LEG_ACCESSORY,
                   accessory=True)],
    "mobility": [Slot("core hold", ("core",), (r"plank", r"dead bug"), None),
                 Slot("back and core", ("back", "core"), (r"bird dog",), r"bird dog|superman|extension|cat",
                      stretch_ok=True),
                 Slot("spine", ("core", "back"), (r"cat.?cow|cat stretch",),
                      r"cat|spinal|spine|twist|rotation|back stretch|child", stretch_ok=True),
                 Slot("hips", ("legs",), (r"hip (circle|flexor)|90/90|pigeon",), r"hip|glute|piriformis|groin",
                      stretch_ok=True),
                 Slot("core", ("core",), (r"dead bug", r"plank", r"pelvic tilt"), None, accessory=True)],
}   # no cardio slots: cardio days are "Cardio of your choice" (see build_day)
# When a required slot has nothing that fits (equipment, injury filter), try these, in order, so a strength day still
# reaches a second muscle group: the same groups with any movement, then the category's other groups not used yet.
CATEGORY_GROUPS = {"upper": ("chest", "back", "shoulders", "arms"), "lower": ("legs",),
                   "mobility": ("core", "back", "legs")}
MIN_SLOTS = {"upper": 4, "lower": 4, "mobility": 5}   # strength: 2 main + at least 2 accessories
MAX_EXERCISES = {"upper": 6, "lower": 6, "mobility": 5}
CIRCUIT_MIN_MINUTES = 15   # mobility days are circuits repeated to fill the session, never under 15 min
EXTRA_SLOTS = {"upper": [SLOTS["upper"][3], SLOTS["upper"][0], SLOTS["upper"][1]],
               "lower": [SLOTS["lower"][2], SLOTS["lower"][3]], "mobility": [SLOTS["mobility"][4]]}


class NoProfile(Exception):
    """The user hasn't taken the quiz."""


# ---------------------------------------------------------------- output models

class PlanExercise(BaseModel):
    exercise_id: str
    name: str
    muscle_group: str
    category: str
    slot: str
    sets: str
    reps: str
    reps_your_call: bool = False         # Getting stronger: reps are the person's own call
    rest_seconds: int
    est_minutes: float
    injury_check: str
    weighted: bool = False               # uses dumbbells, kettlebells, ...: shows a weight field (else blank)
    load: Literal["arms", "legs"] | None = None
    default_weight_lb: float | None = None
    swapped_from: str | None = None      # review mode: the generated exercise this one replaced


class PlanDay(BaseModel):
    day: str
    kind: Literal["training", "rest"]
    category: str | None = None
    focus: str | None = None
    exercises: list[PlanExercise] = []
    est_minutes: float = 0


class PlanWeek(BaseModel):
    week_in_block: int                   # 1..block_weeks
    days: list[PlanDay]


class ProtocolSummary(BaseModel):
    goal: str
    experience_level: str
    session_length_minutes: int
    sets_range: str
    reps_range: str
    rest_seconds: int
    progression_note: str
    status: str
    review_notice: str | None
    citations: list[dict]


class InjuryCaution(BaseModel):
    injury: str
    reasoning: str | None
    tier: str | None
    source: str | None


class LeftOutExercise(BaseModel):
    exercise_id: str
    name: str
    muscle_group: str
    cautions: list[InjuryCaution]        # only the user's own flags


class SafetySummary(BaseModel):
    injury_flags: list[str]
    checked_only: bool
    excluded_as_contraindicated: int
    left_out_for_injury: list[LeftOutExercise] = []
    equipment: list[str] | None          # None = any equipment (full gym)


class WeightScheduleRow(BaseModel):
    exercise_id: str
    name: str
    load: Literal["arms", "legs"]
    weeks: list[int]                     # the weeks (of the schedule) it's on the plan
    weight_lb: list[float | None]        # suggested weight in each of those weeks, from the defaults


class WeightPlan(BaseModel):
    rule: str
    calibration: str
    defaults_lb: dict | None             # this experience level's starting weights (None = bodyweight only)
    step_lb: dict
    schedule_weeks: int
    schedule: list[WeightScheduleRow]


class WeeklyProgram(BaseModel):
    generated: bool
    blocked_reason: str | None = None
    needs_clinical_review: bool = False
    goal: str
    goal_label: str
    experience_level: str
    training_days: int = 0
    block_weeks: int = 0
    plan_weeks: int = 0                  # how long the plan runs: 26 weeks (6 months), the block repeating throughout
    weeks: list[PlanWeek] = []
    days: list[PlanDay] = []             # week 1 (the same as weeks[0].days), for single-week views
    protocol: ProtocolSummary | None = None
    safety: SafetySummary | None = None
    notes: list[str] = []
    weights: WeightPlan | None = None
    # Review mode only: for each generated exercise id, what it may be swapped for (same slot, same filters).
    swap_options: dict[str, list[dict]] | None = None


# ---------------------------------------------------------------- protocol

@dataclass(frozen=True)
class Protocol:
    goal: str
    experience_level: str
    session_length_minutes: int
    sets: tuple[int, int]
    reps: tuple[int, int]
    rest_seconds: int
    progression_note: str
    status: str
    citations: tuple = ()


def parse_range(text: str) -> tuple[int, int]:
    parts = str(text).replace(" ", "").split("-")
    return int(parts[0]), int(parts[-1])


def fmt_range(lo: int, hi: int) -> str:
    return str(lo) if lo == hi else f"{lo}-{hi}"


def load_protocol(goal: str, experience_level: str) -> Protocol:
    conn = connect_readonly()
    try:
        r = conn.execute("SELECT * FROM goal_protocols WHERE goal = ? AND experience_level = ?",
                         (goal, experience_level)).fetchone()
    finally:
        conn.close()
    if r is None:
        raise ValueError(f"No goal_protocols row for {goal}/{experience_level}")
    return Protocol(goal=r["goal"], experience_level=r["experience_level"],
                    session_length_minutes=r["session_length_minutes"], sets=parse_range(r["sets_range"]),
                    reps=parse_range(r["reps_range"]), rest_seconds=r["rest_seconds"],
                    progression_note=r["progression_note"], status=r["status"],
                    citations=tuple(json.loads(r["citations"])))


# ---------------------------------------------------------------- weights

def variant_of(week: int, block_weeks: int) -> int:
    """Which week of the repeating block a plan week is (0-based). Week 1 = variant 0."""
    return (max(1, week) - 1) % block_weeks


def weight_steps(goal: str, block_weeks: int, appears_in: set[int], anchor_week: int, week: int) -> int:
    """How many automatic increases between the anchor (where the weight was last set: the default in week 1, or a
    logged weight) and `week`. Getting stronger: one per time this exercise's day comes round again. Losing weight:
    one per new 4-week block. Feeling good: none."""
    if week <= anchor_week:
        return 0
    if goal == "stronger":
        return sum(1 for w in range(anchor_week + 1, week + 1) if variant_of(w, block_weeks) in appears_in)
    if goal == "lose_weight":
        return (week - 1) // LOSE_WEIGHT_STEP_WEEKS - (anchor_week - 1) // LOSE_WEIGHT_STEP_WEEKS
    return 0


def first_week(appears_in: set[int]) -> int:
    """The plan week an exercise first appears in (its default weight's anchor: the first time isn't "again")."""
    return min(appears_in) + 1 if appears_in else 1


def suggested_weight(goal: str, load: str, base: float | None, steps: int) -> float | None:
    if base is None:
        return None
    w = base + steps * WEIGHT_STEP_LB[goal][load]
    return int(w) if float(w).is_integer() else round(w, 1)


def default_weight(experience_level: str, load: str | None) -> float | None:
    d = DEFAULT_WEIGHT_LB.get(experience_level)
    return d[load] if d and load else None


def is_weighted(category: str, equipment_needed: list[str]) -> bool:
    return category in STRENGTH and bool(WEIGHTED_EQUIPMENT & set(equipment_needed))


# ---------------------------------------------------------------- picking

def available_equipment(quiz_equipment: list[str]) -> list[str] | None:
    if "full_gym" in quiz_equipment:
        return None
    have = set(HOUSEHOLD)
    for item in quiz_equipment:
        have.update(QUIZ_EQUIPMENT.get(item, []))
    return sorted(have)


def slot_label(category: str, slot: Slot) -> str:
    label = CATEGORY_LABELS[category].lower()
    return label if slot.name == label else f"{label} ({slot.name})"


def _movement(e: dict) -> str:
    return f"{e['name']} {' '.join(e.get('primary_muscles') or [])}".lower()


@dataclass
class Picker:
    """Picks exercises for slots from the shared, injury-filtered search. Rotates through each slot's ranked pool."""
    equipment: list[str] | None
    injury_flags: list[str]
    checked_only: bool
    experience_level: str
    low_impact: bool
    group_pool: dict[str, list[dict]] = field(default_factory=dict)
    excluded: int = 0
    turn: dict[tuple[str, str], int] = field(default_factory=dict)   # (category, slot) -> how many times used
    empty: set[str] = field(default_factory=set)

    def group(self, g: str) -> list[dict]:
        if g not in self.group_pool:
            # The SAME tested filter as the MCP tool: injury contraindications are removed in SQL, and checked_only
            # (always on with an injury flag) drops exercises nobody has drafted injury data for.
            result = search_all_exercises(muscle_group=g, equipment=self.equipment, injury_flags=self.injury_flags,
                                          checked_only=self.checked_only)
            self.excluded += result["injury_filter"]["excluded_as_contraindicated"]
            allowed = DIFFICULTY_ALLOWED[self.experience_level]
            self.group_pool[g] = [e for e in result["exercises"] if e["difficulty"] in allowed
                                  and not (self.low_impact and (e["category"] == "plyometrics"
                                                                or HIGH_IMPACT.search(e["name"])))]
        return self.group_pool[g]

    def ranked(self, category: str, slot: Slot) -> list[dict]:
        """The slot's candidates: backbone matches first (in the backbone's order), then the rest of the slot."""
        pool, seen = [], set()
        for g in slot.groups:
            for e in self.group(g):
                if e["id"] in seen:
                    continue
                cat = e["category"]
                if category == "mobility":   # core work, and stretches where the slot is about mobility
                    ok = (cat in (None, "strength") or (slot.stretch_ok and cat == "stretching")) and \
                         (slot.match is None or bool(re.search(slot.match, _movement(e))))
                else:
                    ok = cat not in NEVER_IN_STRENGTH and (slot.match is None or re.search(slot.match, _movement(e)))
                if self.equipment is not None and NEEDS_BAR.search(e["name"]):
                    ok = False
                if category == "mobility" and WEIGHTED_EQUIPMENT & set(e["equipment_needed"]):
                    ok = False
                if ok:
                    seen.add(e["id"])
                    pool.append(e)

        def rank(e):
            name = e["name"].lower()
            hits = [i for i, p in enumerate(slot.backbone) if re.search(p, name)]
            # backbone order first; then the hand-authored home moves; then checked before unchecked; then name
            return (min(hits) if hits else len(slot.backbone), e["source_dataset"] != "placeholder-authored",
                    e["injury_unchecked"], e["name"])
        return sorted(pool, key=rank)

    def backbone_count(self, slot: Slot, ranked: list[dict]) -> int:
        return sum(1 for e in ranked if any(re.search(p, e["name"].lower()) for p in slot.backbone))

    def pick(self, category: str, slot: Slot, used_today: set[str], required: bool = True) -> dict | None:
        # used_today holds ids AND lower-cased names: the library has a few same-name entries from the two sources
        taken = [f for f in ONE_PER_DAY if any(f.search(u) for u in used_today)]
        ranked = [e for e in self.ranked(category, slot)
                  if e["id"] not in used_today and e["name"].lower() not in used_today
                  and not any(f.search(e["name"]) for f in taken)]
        if not ranked:
            if required:
                self.empty.add(slot_label(category, slot))
            return None
        key = (category, slot.name)
        n = self.turn.get(key, 0)
        self.turn[key] = n + 1
        # Main slots rotate through the backbone moves (the most effective, easiest-at-home ones) when there are any;
        # accessories rotate through the whole slot for variety.
        top = self.backbone_count(slot, ranked)
        span = top if (top and not slot.accessory) else len(ranked)
        return ranked[n % span]


def _exercise(e: dict, category: str, slot: Slot, p: Protocol, goal: str, experience: str) -> tuple[PlanExercise, int]:
    """One planned exercise and its time in seconds."""
    if category == "mobility":   # one round; build_day sets how many rounds fill the session
        hold = bool(HOLD.search(e["name"])) or e["category"] == "stretching"
        sets, reps, rest = "1", MOBILITY_HOLD if hold else "8-10 slow", MOBILITY_REST
        seconds = (30 if hold else e["est_time_seconds"]) + MOBILITY_REST
    else:
        hold = bool(HOLD.search(e["name"]))
        sets = fmt_range(*p.sets)
        reps = f"{p.reps[0] * 2}-{p.reps[1] * 2}s hold" if hold else fmt_range(*p.reps)
        rest = p.rest_seconds
        seconds = p.sets[1] * e["est_time_seconds"] + (p.sets[1] - 1) * p.rest_seconds
    load = ("arms" if category == "upper" else "legs") if category in STRENGTH else None
    weighted = is_weighted(category, e["equipment_needed"])
    return PlanExercise(
        exercise_id=e["id"], name=e["name"], muscle_group=e["muscle_group"], category=category, slot=slot.name,
        sets=sets, reps=reps, reps_your_call=goal == "stronger" and category in STRENGTH and not HOLD.search(e["name"]),
        rest_seconds=rest, est_minutes=round(seconds / 60, 1), injury_check=e["injury_check"], weighted=weighted,
        load=load if weighted else None, default_weight_lb=default_weight(experience, load) if weighted else None,
    ), seconds


def relaxed_slots(category: str, slot: Slot, groups_used: set[str]) -> list[Slot]:
    stretch = category == "mobility"
    others = tuple(g for g in CATEGORY_GROUPS[category] if g not in groups_used and g not in slot.groups)
    out = [Slot(slot.name, slot.groups, slot.backbone, None, slot.accessory, stretch)]
    if others:
        out.append(Slot(slot.name, others, (), None, slot.accessory, stretch))
    return out


def build_day(day: str, category: str, picker: Picker, p: Protocol, goal: str, experience: str,
              slots_used: dict) -> PlanDay:
    """Fill the required slots (strength: 2 main + 2 accessories), then extras while there's time."""
    if category == "cardio":   # nothing prescribed: the person does whatever cardio they like and logs it
        return PlanDay(day=day, kind="training", category="cardio", focus=CATEGORY_LABELS["cardio"], exercises=[],
                       est_minutes=0)
    budget = p.session_length_minutes * 60
    exercises: list[PlanExercise] = []
    used: set[str] = set()
    total = 0
    plan = SLOTS[category][: MIN_SLOTS[category]] + EXTRA_SLOTS[category] * 3
    for i, slot in enumerate(plan):
        if len(exercises) >= MAX_EXERCISES[category]:
            break
        required = i < MIN_SLOTS[category]
        e = picker.pick(category, slot, used, required=False)
        if e is None and required:
            for relaxed in relaxed_slots(category, slot, {x.muscle_group for x in exercises}):
                e = picker.pick(category, relaxed, used, required=False)
                if e is not None:
                    slot = relaxed
                    break
            if e is None:
                picker.empty.add(slot_label(category, slot))
        if e is None:
            continue
        x, seconds = _exercise(e, category, slot, p, goal, experience)
        if not required and total + seconds > budget:
            picker.turn[(category, slot.name)] -= 1   # not used after all
            break
        used.update({e["id"], e["name"].lower()})
        slots_used[(day, len(exercises))] = slot
        exercises.append(x)
        total += seconds
    if category == "mobility" and exercises:
        # A circuit: go round all the moves as many whole rounds as fit in the session, but at least 2 rounds and
        # at least 15 minutes.
        per_round = max(1, total)
        rounds = max(2, budget // per_round, -(-CIRCUIT_MIN_MINUTES * 60 // per_round))
        exercises = [x.model_copy(update={"sets": str(rounds), "est_minutes": round(x.est_minutes * rounds, 1)})
                     for x in exercises]
        total *= rounds
    return PlanDay(day=day, kind="training", category=category, focus=CATEGORY_LABELS[category],
                   exercises=exercises, est_minutes=round(total / 60, 1))


# ---------------------------------------------------------------- review-mode swaps

def _apply_swaps(weeks: list[PlanWeek], slots: dict, picker: Picker, p: Protocol, goal: str, experience: str,
                 swaps: dict[str, str]) -> tuple[list[PlanWeek], dict[str, list[dict]]]:
    """Options for every generated exercise, and the plan with valid swaps applied everywhere that exercise appears.
    A swap only counts if the replacement is in that slot's filtered pool right now, so it can never bring in an
    exercise the injury filter would remove (checked again on every generation, not just when it was saved)."""
    options: dict[str, list[dict]] = {}
    out = []
    for w in weeks:
        days = []
        for d in w.days:
            if d.kind != "training":
                days.append(d)
                continue
            used = {x.exercise_id for x in d.exercises}
            exercises, changed = [], False
            for i, x in enumerate(d.exercises):
                slot = slots[(w.week_in_block, d.day, i)]
                pool = [e for e in picker.ranked(d.category, slot) if e["id"] == x.exercise_id or e["id"] not in used]
                options.setdefault(x.exercise_id, [])
                known = {o["id"] for o in options[x.exercise_id]}
                options[x.exercise_id] += [{"id": e["id"], "name": e["name"], "injury_check": e["injury_check"]}
                                           for e in pool if e["id"] != x.exercise_id and e["id"] not in known]
                want = swaps.get(x.exercise_id)
                choice = next((e for e in pool if e["id"] == want and want != x.exercise_id), None)
                if choice is None:
                    exercises.append(x)
                    continue
                new, _ = _exercise(choice, d.category, slot, p, goal, experience)
                if d.category == "mobility":   # a circuit: keep the day's number of rounds
                    new = new.model_copy(update={"sets": x.sets, "est_minutes": x.est_minutes})
                exercises.append(new.model_copy(update={"swapped_from": x.exercise_id}))
                used.add(choice["id"])
                changed = True
            if changed:
                days.append(d.model_copy(update={"exercises": exercises,
                                                 "est_minutes": round(sum(x.est_minutes for x in exercises), 1)}))
            else:
                days.append(d)
        out.append(w.model_copy(update={"days": days}))
    return out, options


# ---------------------------------------------------------------- the weight schedule shown with the plan

def weight_plan(goal: str, experience: str, weeks: list[PlanWeek]) -> WeightPlan:
    """Suggested weights week by week from the defaults (before anything is logged), so the plan can show the climb.
    Covers the whole 6-month plan (PLAN_WEEKS)."""
    block = len(weeks)
    n_weeks = PLAN_WEEKS
    appears: dict[str, tuple[PlanExercise, set[int]]] = {}
    for w in weeks:
        for d in w.days:
            for x in d.exercises:
                if x.weighted:
                    appears.setdefault(x.exercise_id, (x, set()))[1].add(w.week_in_block - 1)
    rows = []
    for ex_id, (x, variants) in appears.items():
        on = [wk for wk in range(1, n_weeks + 1) if variant_of(wk, block) in variants]
        base = default_weight(experience, x.load)
        rows.append(WeightScheduleRow(
            exercise_id=ex_id, name=x.name, load=x.load, weeks=on,
            weight_lb=[suggested_weight(goal, x.load, base,
                                        weight_steps(goal, block, variants, first_week(variants), wk)) for wk in on]))
    return WeightPlan(rule=WEIGHT_RULES[goal], calibration=CALIBRATION_NOTE, defaults_lb=DEFAULT_WEIGHT_LB[experience],
                      step_lb=WEIGHT_STEP_LB[goal], schedule_weeks=n_weeks, schedule=rows)


# ---------------------------------------------------------------- the generator

def generate(profile: dict, swaps: dict[str, str] | None = None, with_swap_options: bool = False) -> WeeklyProgram:
    """Build the plan for a quiz profile (dict with the quiz_profiles columns, lists decoded).
    swaps (review mode): {generated exercise id: replacement id}, applied only where valid (see _apply_swaps)."""
    goal = profile.get("goal") if profile.get("goal") in GOALS else "feel_good"
    experience = profile.get("experience_level") or "beginner"
    flags = sorted(set(profile.get("injury_flags") or []))
    notes: list[str] = []
    if needs_clinical_review(profile.get("pregnancy_status")):
        return WeeklyProgram(generated=False, blocked_reason=CLINICAL_REVIEW_MESSAGE, needs_clinical_review=True,
                             goal=goal, goal_label=GOAL_LABELS[goal], experience_level=experience,
                             days=[PlanDay(day=d, kind="rest") for d in WEEK])

    p = load_protocol(goal, experience)
    checked_only = checked_only_for(flags)        # no exceptions: an injury flag always means checked_only
    picker = Picker(equipment=available_equipment(profile.get("equipment") or ["bodyweight"]), injury_flags=flags,
                    checked_only=checked_only, experience_level=experience,
                    low_impact=experience == "beginner" or bool(flags))
    weeks, slots = [], {}
    for i, layout in enumerate(STRUCTURES[goal], start=1):
        days, used = [], {}
        for day in WEEK:
            if day in layout:
                days.append(build_day(day, layout[day], picker, p, goal, experience, used))
            else:
                days.append(PlanDay(day=day, kind="rest"))
        slots.update({(i, d, n): s for (d, n), s in used.items()})
        weeks.append(PlanWeek(week_in_block=i, days=days))
    swap_options = None
    if swaps or with_swap_options:
        weeks, swap_options = _apply_swaps(weeks, slots, picker, p, goal, experience, swaps or {})

    notes.append(CALIBRATION_NOTE)
    if picker.empty:
        reason = "your equipment" + (" and the injury filter" if checked_only else "")
        notes.append("We couldn't find exercises for " + ", ".join(sorted(picker.empty))
                     + f" that fit {reason}, so those spots were left out.")
    if checked_only:
        notes.append("Because you flagged an injury, every exercise here has drafted injury data, and anything tagged "
                     "as unsafe for " + ", ".join(f.replace("_", " ") for f in flags) + " was left out. The tags are "
                     "drafts a physical therapist hasn't reviewed yet, so stop anything that hurts.")
    elif any(x.injury_check == "not_yet_checked" for w in weeks for d in w.days for x in d.exercises):
        notes.append("Some exercises haven't been checked for injury safety yet (they're marked). Skip anything "
                     "that doesn't feel right.")

    return WeeklyProgram(
        generated=True, goal=goal, goal_label=GOAL_LABELS[goal], experience_level=experience,
        training_days=TRAINING_DAYS, block_weeks=BLOCK_WEEKS[goal], plan_weeks=PLAN_WEEKS, weeks=weeks,
        days=weeks[0].days, notes=notes,
        protocol=ProtocolSummary(
            goal=goal, experience_level=experience, session_length_minutes=p.session_length_minutes,
            sets_range=fmt_range(*p.sets), reps_range=fmt_range(*p.reps), rest_seconds=p.rest_seconds,
            progression_note=p.progression_note, status=p.status,
            review_notice=REVIEW_NOTICE if p.status == "placeholder" else None, citations=list(p.citations)),
        weights=weight_plan(goal, experience, weeks),
        swap_options=swap_options if with_swap_options else None,
        safety=SafetySummary(injury_flags=flags, checked_only=checked_only, excluded_as_contraindicated=picker.excluded,
                             equipment=picker.equipment,
                             # only the muscle groups this plan actually draws from (as excluded_as_contraindicated)
                             left_out_for_injury=contraindicated_exercises(flags, sorted(picker.group_pool),
                                                                           picker.equipment, checked_only)),
    )


PROFILE_COLUMNS = ("goal", "injury_flags", "experience_level", "equipment", "pregnancy_status", "plan_swaps")


def generate_for_user(user_id: int, with_swap_options: bool = False) -> WeeklyProgram:
    conn = connect_readonly()
    try:
        row = conn.execute(f"SELECT {', '.join(PROFILE_COLUMNS)} FROM quiz_profiles WHERE user_id = ?",
                           (user_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise NoProfile("Take the quiz first so we can build your plan.")
    profile = dict(row)
    for col in ("injury_flags", "equipment"):
        profile[col] = json.loads(profile[col] or "[]")
    swaps = json.loads(profile.pop("plan_swaps") or "{}")
    return generate(profile, swaps=swaps, with_swap_options=with_swap_options)


# ---------------------------------------------------------------- the public worked example
#
# The "How We Build Your Plan" page shows a real run of generate() for this fixed profile, so the example
# can never drift from the algorithm. Nothing here is hand-written output.

EXAMPLE_PROFILE = {
    "goal": "feel_good",
    "experience_level": "beginner",
    "injury_flags": ["lower_back"],
    "equipment": ["bodyweight", "resistance_band"],   # bodyweight is always included
    "pregnancy_status": "none",
}


class FilterStep(BaseModel):
    step: str
    exercises_left: int
    removed: int


class PlanExample(BaseModel):
    profile: dict
    funnel: list[FilterStep]
    plan: WeeklyProgram


def filter_funnel(profile: dict) -> list[FilterStep]:
    """How many exercises in the whole library survive each safety/equipment filter, in the order the page
    explains them. Counted live with the same search the generator uses."""
    flags = sorted(set(profile.get("injury_flags") or []))
    equipment = available_equipment(profile.get("equipment") or ["bodyweight"])
    stages = [("The whole exercise library", {})]
    if flags:
        stages += [
            ("Remove exercises tagged unsafe for " + ", ".join(f.replace("_", " ") for f in flags),
             {"injury_flags": flags}),
            ("Remove exercises nobody has checked for injuries yet",
             {"injury_flags": flags, "checked_only": checked_only_for(flags)}),
        ]
    stages.append(("Keep only what your equipment allows",
                   {"injury_flags": flags, "checked_only": checked_only_for(flags), "equipment": equipment}))
    steps, previous = [], None
    for label, kwargs in stages:
        left = search_all_exercises(**kwargs)["total_matching"]
        steps.append(FilterStep(step=label, exercises_left=left, removed=0 if previous is None else previous - left))
        previous = left
    return steps


def worked_example() -> PlanExample:
    return PlanExample(profile=EXAMPLE_PROFILE, funnel=filter_funnel(EXAMPLE_PROFILE), plan=generate(EXAMPLE_PROFILE))

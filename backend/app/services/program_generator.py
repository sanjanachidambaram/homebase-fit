"""Deterministic weekly program generator. Plain Python: there is NO LLM call anywhere in this module.

Input: the user's quiz profile. Output: a WeeklyProgram (every day of the week, training or rest).

How a plan is built (each step is a named function below, and the rules are in shared_rules.md, rule 6):
  1. Safety first. Pregnant/postpartum -> no plan (needs OB-GYN-reviewed guidance first). Any injury flag
     -> checked_only=true for every exercise search (app/safety_rules.py), no exceptions.
  2. Look up the goal_protocols row for each chosen goal at the user's experience level, and BLEND them
     (blend_protocols): where they differ, take the more conservative value.
  3. Training days = min(days the user has, protocol sessions), always leaving at least one full rest day,
     and fewer if other regular activity would push the week past 6 active days (training_day_count).
  4. Each training day gets muscle groups from the split type, and exercises are picked with the EXISTING,
     tested injury filter: app.mcp_server.search.search_exercises (the same SQL the MCP tool uses).
  5. Sets, reps, and rest come from the blended protocol, never invented per exercise.
Same profile in, same plan out.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from app.content import REVIEW_NOTICE
from app.db import connect_readonly
from app.mcp_server.search import contraindicated_exercises, search_exercises
from app.safety_rules import checked_only_for, needs_clinical_review

GOALS = ("weight_loss", "strength", "tone", "rehab", "general_health")
# Most to least conservative, for ordering notes and picking the "safest" goal's wording.
GOAL_CAUTION = ("rehab", "general_health", "weight_loss", "tone", "strength")
# Most to least conservative split: full-body spreads the load thinnest per muscle per session.
SPLIT_CAUTION = ("full_body", "circuit", "upper_lower", "push_pull_legs")
WEEK = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
MAX_ACTIVE_DAYS = 6          # training + other regular activity; at least one full rest day a week
# Which weekdays to train for N sessions: spread out, with rest days between where possible.
DAY_PATTERNS = {
    1: ("wed",), 2: ("mon", "thu"), 3: ("mon", "wed", "fri"), 4: ("mon", "tue", "thu", "fri"),
    5: ("mon", "tue", "wed", "fri", "sat"), 6: ("mon", "tue", "wed", "thu", "fri", "sat"),
}
# Day templates per split: (label, muscle groups in the order they're filled, movement direction or None).
# A direction keeps the opposite one out of that day's upper-body slots: a Push day never gets a curl or a row,
# and a Pull day never gets a push-up or a dip (exercises.force). Static and unclassified moves stay allowed.
DAY_TEMPLATES = {
    "full_body": [("Full body A", ["legs", "back", "chest", "core", "shoulders", "arms", "full_body", "legs"], None),
                  ("Full body B", ["legs", "chest", "back", "core", "arms", "shoulders", "full_body", "core"], None)],
    "circuit": [("Full-body circuit", ["full_body", "legs", "back", "core", "chest", "shoulders", "arms", "legs"],
                 None)],
    "upper_lower": [("Upper body", ["chest", "back", "shoulders", "arms", "core", "back", "chest", "arms"], None),
                    ("Lower body + core", ["legs", "core", "legs", "full_body", "legs", "core", "legs", "core"], None)],
    "push_pull_legs": [("Push", ["chest", "shoulders", "arms", "chest", "core", "shoulders", "arms", "core"], "push"),
                       ("Pull", ["back", "arms", "back", "core", "shoulders", "back", "arms", "core"], "pull"),
                       ("Legs", ["legs", "legs", "core", "legs", "full_body", "legs", "core", "legs"], None)],
}
DIRECTIONAL_GROUPS = {"chest", "shoulders", "arms", "back"}   # where push vs pull matters
OPPOSITE = {"push": "pull", "pull": "push"}
# Quiz equipment answers -> equipment values in the exercise library. None = no equipment filter.
QUIZ_EQUIPMENT = {
    "bodyweight": ["none"], "dumbbells": ["dumbbells"], "resistance_band": ["resistance_band"], "mat": ["mat"],
    "bench": ["bench"], "kettlebells": ["kettlebells"],
    "pull_up_bar": [],   # no exercise in the library is tagged with a bar yet
}
HOUSEHOLD = ("none", "chair")   # bodyweight moves and a sturdy chair are assumed available at home
NEVER_IN_PLANS = {"olympic weightlifting", "strongman", "powerlifting", "stretching"}
DIFFICULTY_ALLOWED = {"beginner": {"beginner"}, "intermediate": {"beginner", "intermediate"},
                      "advanced": {"beginner", "intermediate", "advanced"}}
MIN_EXERCISES, MAX_EXERCISES = 2, 8
SEARCH_LIMIT = 50
HOLD = re.compile(r"\b(plank|hold|wall sit)\b", re.I)
# Jumping and landing moves are left out of low-impact plans (rehab, any injury flag, or beginners).
HIGH_IMPACT = re.compile(r"jump|burpee|\bhop|bound|skater|plyo|tuck", re.I)
CLINICAL_REVIEW_MESSAGE = (
    "Because you're pregnant or postpartum, we're not generating a plan yet. Exercise during and after "
    "pregnancy needs guidance from a clinician, and ours is still waiting on review by an OB-GYN. Please talk "
    "with your OB-GYN or midwife about what's right for you."
)


class NoProfile(Exception):
    """The user hasn't taken the quiz."""


# ---------------------------------------------------------------- output models

class PlanExercise(BaseModel):
    exercise_id: str
    name: str
    muscle_group: str
    sets: str
    reps: str
    rest_seconds: int
    est_minutes: float
    injury_check: str


class PlanDay(BaseModel):
    day: str
    kind: Literal["training", "rest"]
    focus: str | None = None
    exercises: list[PlanExercise] = []
    est_minutes: float = 0


class ProtocolSummary(BaseModel):
    goals_used: list[str]
    experience_level: str
    split_type: str
    sessions_per_week: int
    session_length_minutes: int
    sets_range: str
    reps_range: str
    rest_seconds: int
    progression_notes: list[str]
    blending_rules_applied: list[str]
    status: str
    review_notice: str | None
    citations: list[dict]


class InjuryCaution(BaseModel):
    injury: str
    reasoning: str | None                # plain-language, AI-drafted until a PT reviews it; never a citation
    tier: str | None                     # ai_drafted | pt_reviewed
    source: str | None                   # "Pending review by a licensed physical therapist", or the PT


class LeftOutExercise(BaseModel):
    exercise_id: str
    name: str
    muscle_group: str
    cautions: list[InjuryCaution]        # only the user's own flags


class SafetySummary(BaseModel):
    injury_flags: list[str]
    checked_only: bool
    excluded_as_contraindicated: int     # tagged-unsafe exercises the filter removed while picking
    # Which ones, and why. Built by code for the person's own plan view; Program Architect never sees it
    # (shared_rules rule 2: injury details stay out of the model's prompt).
    left_out_for_injury: list[LeftOutExercise] = []
    equipment: list[str] | None          # None = any equipment (full gym)


class WeeklyProgram(BaseModel):
    generated: bool
    blocked_reason: str | None = None
    needs_clinical_review: bool = False
    goals: list[str]
    experience_level: str
    training_days: int = 0
    days: list[PlanDay] = []
    protocol: ProtocolSummary | None = None
    safety: SafetySummary | None = None
    notes: list[str] = []


# ---------------------------------------------------------------- protocols and blending

def parse_range(text: str) -> tuple[int, int]:
    parts = str(text).replace(" ", "").split("-")
    return int(parts[0]), int(parts[-1])


def fmt_range(lo: int, hi: int) -> str:
    return str(lo) if lo == hi else f"{lo}-{hi}"


@dataclass(frozen=True)
class Protocol:
    goal: str
    experience_level: str
    sessions_per_week: int
    session_length_minutes: int
    split_type: str
    sets: tuple[int, int]
    reps: tuple[int, int]
    rest_seconds: int
    progression_note: str
    status: str
    citations: tuple = ()


@dataclass
class Blended:
    goals: list[str]
    sessions_per_week: int
    session_length_minutes: int
    split_type: str
    sets: tuple[int, int]
    reps: tuple[int, int]
    rest_seconds: int
    progression_notes: list[str]
    status: str
    citations: list[dict]
    rules: list[str] = field(default_factory=list)


def blend_protocols(protocols: list[Protocol]) -> Blended:
    """Combine one protocol per goal. Where they differ, the more conservative value wins:
    fewest sessions, shortest sessions, the gentlest split, the lower set range, the lighter-load
    (higher-rep) range, and the longest rest. Placeholder status wins over reviewed."""
    if not protocols:
        raise ValueError("blend_protocols needs at least one protocol")
    ps = sorted(protocols, key=lambda p: GOAL_CAUTION.index(p.goal))
    rules = []
    if len(ps) > 1:
        rules = [
            "sessions per week: the fewest of the goals",
            "session length: the shortest of the goals",
            "split: the gentlest (full body > circuit > upper/lower > push/pull/legs)",
            "sets: the lower range",
            "reps: the lighter-load (higher-rep) range",
            "rest: the longest",
        ]
    citations, seen = [], set()
    for p in ps:
        for c in p.citations:
            key = (c.get("claim"), c.get("source"))
            if key not in seen:
                seen.add(key)
                citations.append(dict(c))
    return Blended(
        goals=[p.goal for p in ps],
        sessions_per_week=min(p.sessions_per_week for p in ps),
        session_length_minutes=min(p.session_length_minutes for p in ps),
        split_type=min((p.split_type for p in ps), key=SPLIT_CAUTION.index),
        sets=(min(p.sets[0] for p in ps), min(p.sets[1] for p in ps)),
        reps=max((p.reps for p in ps), key=lambda r: (r[0], r[1])),
        rest_seconds=max(p.rest_seconds for p in ps),
        progression_notes=[f"{p.goal.replace('_', ' ')}: {p.progression_note}" for p in ps],
        status="pt_reviewed" if all(p.status == "pt_reviewed" for p in ps) else "placeholder",
        citations=citations,
        rules=rules,
    )


def load_protocols(goals: list[str], experience_level: str) -> list[Protocol]:
    conn = connect_readonly()
    try:
        rows = conn.execute(
            f"SELECT * FROM goal_protocols WHERE experience_level = ? AND goal IN ({','.join('?' * len(goals))})",
            (experience_level, *goals)).fetchall()
    finally:
        conn.close()
    return [Protocol(goal=r["goal"], experience_level=r["experience_level"], sessions_per_week=r["sessions_per_week"],
                     session_length_minutes=r["session_length_minutes"], split_type=r["split_type"],
                     sets=parse_range(r["sets_range"]), reps=parse_range(r["reps_range"]),
                     rest_seconds=r["rest_seconds"], progression_note=r["progression_note"], status=r["status"],
                     citations=tuple(json.loads(r["citations"]))) for r in rows]


# ---------------------------------------------------------------- days

def training_day_count(days_available: int, sessions_per_week: int, other_activity_days: int) -> tuple[int, list[str]]:
    """min(available days, protocol sessions), always leaving a full rest day, and fewer if other regular
    activity would push the week past MAX_ACTIVE_DAYS active days. Never less than one session."""
    notes = []
    n = min(days_available, sessions_per_week, MAX_ACTIVE_DAYS)
    if days_available > sessions_per_week:
        notes.append(f"Your plan uses {sessions_per_week} of the {days_available} days you have: that's what "
                     "the protocol for your goals calls for. Spare days are rest or easy movement.")
    if days_available >= 7 and sessions_per_week >= 7:
        notes.append("We always keep at least one full rest day.")
    room = MAX_ACTIVE_DAYS - other_activity_days
    if n > room:
        n = max(1, room)
        notes.append(f"You already do other activity {other_activity_days} day(s) a week, so we planned {n} "
                     f"session(s) to keep at least one full rest day.")
    return max(1, n), notes


# ---------------------------------------------------------------- exercise picking

def available_equipment(quiz_equipment: list[str]) -> list[str] | None:
    if "full_gym" in quiz_equipment:
        return None
    have = set(HOUSEHOLD)
    for item in quiz_equipment:
        have.update(QUIZ_EQUIPMENT.get(item, []))
    return sorted(have)


def is_hold(name: str) -> bool:
    return bool(HOLD.search(name))


@dataclass
class Picker:
    """Picks exercises for slots, using the shared injury filter. Remembers what it's used this week."""
    equipment: list[str] | None
    injury_flags: list[str]
    checked_only: bool
    experience_level: str
    low_impact: bool
    candidates: dict[str, list[dict]] = field(default_factory=dict)
    week_use: dict[str, int] = field(default_factory=dict)
    excluded: int = 0
    empty_groups: set[str] = field(default_factory=set)

    def pool(self, group: str) -> list[dict]:
        if group not in self.candidates:
            # The SAME tested filter as the MCP tool: injury contraindications are removed in SQL, and
            # checked_only (always on with an injury flag) drops exercises nobody has tagged.
            result = search_exercises(muscle_group=group, equipment=self.equipment, injury_flags=self.injury_flags,
                                      limit=SEARCH_LIMIT, checked_only=self.checked_only)
            self.excluded += result["injury_filter"]["excluded_as_contraindicated"]
            allowed = DIFFICULTY_ALLOWED[self.experience_level]
            self.candidates[group] = [
                e for e in result["exercises"]
                if e["difficulty"] in allowed and e["category"] not in NEVER_IN_PLANS
                and not (self.low_impact and (e["category"] == "plyometrics" or HIGH_IMPACT.search(e["name"])))
            ]
        return self.candidates[group]

    def pick(self, group: str, used_today: set[str], direction: str | None = None) -> dict | None:
        allowed = self.pool(group)
        if direction and group in DIRECTIONAL_GROUPS:   # Push/Pull days: never the opposite movement
            allowed = [e for e in allowed if e.get("force") != OPPOSITE[direction]]
        options = [(self.week_use.get(e["id"], 0), i, e) for i, e in enumerate(allowed) if e["id"] not in used_today]
        if not options:
            if not self.pool(group):
                self.empty_groups.add(group)
            elif not allowed:
                self.empty_groups.add(f"{direction}ing {group}")
            return None
        _, _, chosen = min(options, key=lambda t: (t[0], t[1]))   # least used this week, then search order
        self.week_use[chosen["id"]] = self.week_use.get(chosen["id"], 0) + 1
        return chosen


def exercise_seconds(est_time_seconds: int, b: Blended) -> int:
    """Time for one exercise at the TOP of the set range (so the session fits even on a full-effort day):
    sets x the exercise's time per set + rest between sets."""
    return b.sets[1] * est_time_seconds + (b.sets[1] - 1) * b.rest_seconds


def build_day(day: str, label: str, groups: list[str], picker: Picker, b: Blended,
              direction: str | None = None) -> PlanDay:
    """Fill the day's muscle-group slots in order (cycling through them again if there's time left)
    until the session length or MAX_EXERCISES is reached."""
    budget = b.session_length_minutes * 60
    exercises: list[PlanExercise] = []
    used_today: set[str] = set()
    total = 0
    for group in (groups * 2)[: MAX_EXERCISES * 2]:
        if len(exercises) >= MAX_EXERCISES:
            break
        e = picker.pick(group, used_today, direction)
        if e is None:
            continue
        seconds = exercise_seconds(e["est_time_seconds"], b)
        if total + seconds > budget and len(exercises) >= MIN_EXERCISES:
            picker.week_use[e["id"]] -= 1   # not used after all
            break
        used_today.add(e["id"])
        total += seconds
        reps = f"{b.reps[0] * 2}-{b.reps[1] * 2}s hold" if is_hold(e["name"]) else fmt_range(*b.reps)
        exercises.append(PlanExercise(
            exercise_id=e["id"], name=e["name"], muscle_group=e["muscle_group"], sets=fmt_range(*b.sets),
            reps=reps, rest_seconds=b.rest_seconds, est_minutes=round(seconds / 60, 1),
            injury_check=e["injury_check"]))
    return PlanDay(day=day, kind="training", focus=label, exercises=exercises, est_minutes=round(total / 60, 1))


# ---------------------------------------------------------------- the generator

def generate(profile: dict) -> WeeklyProgram:
    """Build the weekly plan for a quiz profile (dict with the quiz_profiles columns, lists decoded)."""
    goals = sorted(set(profile.get("goals") or [])) or ["general_health"]
    experience = profile.get("experience_level") or "beginner"
    flags = sorted(set(profile.get("injury_flags") or []))
    notes: list[str] = []
    missing = [k for k in ("experience_level", "days_available", "session_length_minutes") if not profile.get(k)]
    if missing:
        notes.append("Retake the quiz to personalize this further: we used defaults for "
                     + ", ".join(m.replace("_", " ") for m in missing) + ".")

    if needs_clinical_review(profile.get("pregnancy_status")):
        return WeeklyProgram(generated=False, blocked_reason=CLINICAL_REVIEW_MESSAGE, needs_clinical_review=True,
                             goals=goals, experience_level=experience, notes=notes,
                             days=[PlanDay(day=d, kind="rest") for d in WEEK])

    b = blend_protocols(load_protocols(goals, experience))
    session_length = min(b.session_length_minutes, profile.get("session_length_minutes") or b.session_length_minutes)
    if session_length < b.session_length_minutes:
        b.session_length_minutes = session_length
    n, day_notes = training_day_count(profile.get("days_available") or 3, b.sessions_per_week,
                                      profile.get("other_activity_days") or 0)
    notes += day_notes

    checked_only = checked_only_for(flags)        # no exceptions: an injury flag always means checked_only
    picker = Picker(equipment=available_equipment(profile.get("equipment") or ["bodyweight"]),
                    injury_flags=flags, checked_only=checked_only, experience_level=experience,
                    low_impact=experience == "beginner" or "rehab" in goals or bool(flags))
    templates = DAY_TEMPLATES[b.split_type]
    training = DAY_PATTERNS[n]
    days = []
    for day in WEEK:
        if day in training:
            label, groups, direction = templates[training.index(day) % len(templates)]
            days.append(build_day(day, label, groups, picker, b, direction))
        else:
            days.append(PlanDay(day=day, kind="rest"))

    if picker.empty_groups:
        reason = "your equipment" + (" and the injury filter" if checked_only else "")
        notes.append("We couldn't find " + ", ".join(sorted(g.replace("_", " ") for g in picker.empty_groups))
                     + f" exercises that fit {reason}, so those were left out.")
    if checked_only:
        notes.append("Because you flagged an injury, every exercise here has injury tags, and anything tagged as "
                     "unsafe for " + ", ".join(f.replace("_", " ") for f in flags) + " was left out. The tags are "
                     "drafts a physical therapist hasn't reviewed yet, so stop anything that hurts.")
    elif any(e.injury_check == "not_yet_checked" for d in days for e in d.exercises):
        notes.append("Some exercises haven't been checked for injury safety yet (they're marked). Skip anything "
                     "that doesn't feel right.")

    return WeeklyProgram(
        generated=True, goals=goals, experience_level=experience, training_days=n, days=days, notes=notes,
        protocol=ProtocolSummary(
            goals_used=b.goals, experience_level=experience, split_type=b.split_type,
            sessions_per_week=b.sessions_per_week, session_length_minutes=b.session_length_minutes,
            sets_range=fmt_range(*b.sets), reps_range=fmt_range(*b.reps), rest_seconds=b.rest_seconds,
            progression_notes=b.progression_notes, blending_rules_applied=b.rules, status=b.status,
            review_notice=REVIEW_NOTICE if b.status == "placeholder" else None, citations=b.citations),
        safety=SafetySummary(injury_flags=flags, checked_only=checked_only, excluded_as_contraindicated=picker.excluded,
                             equipment=picker.equipment,
                             left_out_for_injury=contraindicated_exercises(flags, sorted(picker.candidates),
                                                                           picker.equipment, checked_only)),
    )


PROFILE_COLUMNS = ("goals", "injury_flags", "experience_level", "days_available", "session_length_minutes",
                   "equipment", "other_activity_days", "pregnancy_status")


def generate_for_user(user_id: int) -> WeeklyProgram:
    conn = connect_readonly()
    try:
        row = conn.execute(f"SELECT {', '.join(PROFILE_COLUMNS)} FROM quiz_profiles WHERE user_id = ?",
                           (user_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise NoProfile("Take the quiz first so we can build your plan.")
    profile = dict(row)
    for col in ("goals", "injury_flags", "equipment"):
        profile[col] = json.loads(profile[col] or "[]")
    return generate(profile)


# ---------------------------------------------------------------- the public worked example
#
# The "How We Build Your Plan" page shows a real run of generate() for this fixed profile, so the example
# can never drift from the algorithm. Nothing here is hand-written output.

EXAMPLE_PROFILE = {
    "age": 45,                               # shown on the page; the generator doesn't use age
    "goals": ["general_health"],
    "experience_level": "beginner",
    "injury_flags": ["lower_back"],
    "equipment": ["resistance_band"],        # resistance bands only
    "days_available": 3,
    "session_length_minutes": 30,
    "other_activity_days": 0,
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
    explains them. Counted live with the same search_exercises() the generator uses."""
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
        left = search_exercises(limit=1, **kwargs)["total_matching"]
        steps.append(FilterStep(step=label, exercises_left=left, removed=0 if previous is None else previous - left))
        previous = left
    return steps


def worked_example() -> PlanExample:
    return PlanExample(profile=EXAMPLE_PROFILE, funnel=filter_funnel(EXAMPLE_PROFILE), plan=generate(EXAMPLE_PROFILE))

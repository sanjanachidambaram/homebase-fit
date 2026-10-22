"""The deterministic program generator: blending rules, training days, and the injury filter during generation.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_program_generator.py -v
"""

import json
import sqlite3

import pytest

from app import config
from app.db import connect_readonly
from app.services import program_generator as gen
from app.services.program_generator import Protocol, blend_protocols, generate, training_day_count

LOWER_BACK_REHAB = {
    "goals": ["weight_loss", "rehab"], "injury_flags": ["lower_back"], "experience_level": "beginner",
    "days_available": 4, "session_length_minutes": 30, "equipment": ["bodyweight", "mat", "resistance_band"],
    "other_activity_days": 0, "pregnancy_status": "none",
}


def protocol(goal, sessions, length, split, sets, reps, rest, status="placeholder", citations=()):
    return Protocol(goal=goal, experience_level="beginner", sessions_per_week=sessions, session_length_minutes=length,
                    split_type=split, sets=sets, reps=reps, rest_seconds=rest, progression_note=f"{goal} note",
                    status=status, citations=tuple(citations))


@pytest.fixture
def search_spy(monkeypatch):
    """Records every exercise search the generator makes (it must use the shared, tested filter)."""
    calls = []
    real = gen.search_exercises

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)
    monkeypatch.setattr(gen, "search_exercises", spy)
    return calls


def contraindications() -> dict[str, tuple[set[str], str]]:
    conn = connect_readonly()
    try:
        return {r["id"]: (set(json.loads(r["injury_contraindications"])), r["contraindication_status"])
                for r in conn.execute("SELECT id, injury_contraindications, contraindication_status FROM exercises")}
    finally:
        conn.close()


def exercises_in(plan):
    return [e for d in plan.days for e in d.exercises]


# ---------------------------------------------------------------- blending rules

def test_blend_takes_the_conservative_value_everywhere():
    b = blend_protocols([
        protocol("weight_loss", 3, 30, "circuit", (2, 3), (12, 15), 30),
        protocol("rehab", 3, 20, "full_body", (1, 2), (10, 12), 60),
    ])
    assert b.goals == ["rehab", "weight_loss"]                  # most conservative goal first
    assert (b.sessions_per_week, b.session_length_minutes) == (3, 20)   # fewest, shortest
    assert b.split_type == "full_body"                          # gentlest split
    assert b.sets == (1, 2)                                     # lower set range
    assert b.reps == (12, 15)                                   # lighter-load (higher-rep) range
    assert b.rest_seconds == 60                                 # longest rest
    assert len(b.rules) == 6 and b.status == "placeholder"


def test_blend_strength_and_tone():
    b = blend_protocols([
        protocol("strength", 4, 45, "upper_lower", (3, 4), (6, 8), 120),
        protocol("tone", 4, 40, "upper_lower", (3, 3), (10, 15), 60),
    ])
    assert (b.sessions_per_week, b.session_length_minutes, b.split_type) == (4, 40, "upper_lower")
    assert (b.sets, b.reps, b.rest_seconds) == ((3, 3), (10, 15), 120)


def test_split_caution_order():
    def split_of(*splits):
        return blend_protocols([protocol("tone", 3, 30, s, (2, 2), (10, 10), 60) for s in splits]).split_type
    assert split_of("push_pull_legs", "upper_lower") == "upper_lower"
    assert split_of("upper_lower", "circuit") == "circuit"
    assert split_of("circuit", "full_body") == "full_body"


def test_one_goal_needs_no_blending_and_status_and_citations_combine():
    single = blend_protocols([protocol("tone", 3, 30, "full_body", (2, 3), (10, 12), 60)])
    assert single.rules == [] and (single.sets, single.reps) == ((2, 3), (10, 12))
    c1, c2 = {"claim": "a", "source": "x"}, {"claim": "b", "source": "y"}
    reviewed = blend_protocols([protocol("tone", 3, 30, "full_body", (2, 3), (10, 12), 60, "pt_reviewed", [c1]),
                                protocol("strength", 3, 40, "full_body", (2, 3), (8, 10), 90, "pt_reviewed", [c1, c2])])
    assert reviewed.status == "pt_reviewed" and reviewed.citations == [c1, c2]   # union, no duplicates
    mixed = blend_protocols([protocol("tone", 3, 30, "full_body", (2, 3), (10, 12), 60, "pt_reviewed", [c1]),
                             protocol("rehab", 3, 20, "full_body", (1, 2), (10, 12), 60)])
    assert mixed.status == "placeholder"      # one unreviewed goal makes the whole plan unreviewed


def test_blend_needs_a_protocol():
    with pytest.raises(ValueError):
        blend_protocols([])


# ---------------------------------------------------------------- training days

@pytest.mark.parametrize("available, sessions, other, expected", [
    (4, 3, 0, 3),     # protocol asks for fewer than you have
    (2, 5, 0, 2),     # you have fewer than the protocol asks for
    (7, 6, 0, 6),     # never 7: a full rest day is kept
    (7, 6, 1, 5),     # 1 day of other activity -> 5 sessions, still a full rest day
    (5, 5, 3, 3),     # lots of other activity -> fewer sessions
    (3, 5, 6, 1),     # always at least one session
    (3, 5, 7, 1),
])
def test_training_day_count(available, sessions, other, expected):
    n, notes = training_day_count(available, sessions, other)
    assert n == expected
    if other and n < min(available, sessions):
        assert any("other activity" in x for x in notes)


def test_every_plan_has_rest_days_in_between(test_db):
    plan = generate(LOWER_BACK_REHAB)
    kinds = [d.kind for d in plan.days]
    assert len(plan.days) == 7 and kinds.count("training") == plan.training_days == 3
    assert [d.day for d in plan.days if d.kind == "training"] == ["mon", "wed", "fri"]
    six = generate({**LOWER_BACK_REHAB, "goals": ["weight_loss"], "experience_level": "advanced", "injury_flags": [],
                    "days_available": 7})
    assert [d.kind for d in six.days].count("rest") >= 2   # advanced weight loss = 5 sessions; 7 days available


# ---------------------------------------------------------------- the injury filter during generation

def test_injury_filter_is_applied_during_generation(test_db, search_spy):
    plan = generate(LOWER_BACK_REHAB)
    assert plan.generated and search_spy, "the generator must use the shared exercise search"
    for call in search_spy:            # every single search was strict
        assert call["checked_only"] is True and call["injury_flags"] == ["lower_back"]
    tags = contraindications()
    for e in exercises_in(plan):
        unsafe, status = tags[e.exercise_id]
        assert "lower_back" not in unsafe, e.name                # nothing tagged unsafe for the flag
        assert status != "untagged" and e.injury_check != "not_yet_checked", e.name   # nothing unchecked
    assert plan.safety.checked_only is True and plan.safety.excluded_as_contraindicated > 0
    names = {e.name for e in exercises_in(plan)}
    assert {"Crunch", "Superman Hold", "Dumbbell Goblet Squat", "Burpee", "Mountain Climber"}.isdisjoint(names)


def test_a_newly_tagged_exercise_is_excluded_too(test_db, search_spy):
    before = {e.exercise_id for e in exercises_in(generate(LOWER_BACK_REHAB))}
    assert "glute_bridge" in before
    conn = sqlite3.connect(config.WORKING_DB)
    with conn:
        conn.execute("UPDATE exercises SET injury_contraindications = '[\"lower_back\"]' WHERE id = 'glute_bridge'")
    conn.close()
    after = {e.exercise_id for e in exercises_in(generate(LOWER_BACK_REHAB))}
    assert "glute_bridge" not in after


def test_every_injury_flag_forces_checked_only(test_db, search_spy):
    for flag in ("knee", "shoulder", "wrist", "ankle"):
        search_spy.clear()
        plan = generate({**LOWER_BACK_REHAB, "goals": ["tone"], "injury_flags": [flag]})
        assert search_spy and all(c["checked_only"] is True and c["injury_flags"] == [flag] for c in search_spy)
        tags = contraindications()
        assert all(flag not in tags[e.exercise_id][0] for e in exercises_in(plan)), flag


def test_no_injury_means_the_full_library(test_db, search_spy):
    plan = generate({**LOWER_BACK_REHAB, "goals": ["tone"], "injury_flags": [], "equipment": ["dumbbells", "mat"]})
    assert all(c["checked_only"] is False for c in search_spy) and plan.safety.checked_only is False
    assert any(e.injury_check == "not_yet_checked" for e in exercises_in(plan))   # imported moves allowed, flagged
    assert any("haven't been checked" in n for n in plan.notes)


def test_rehab_plans_are_low_impact(test_db):
    plan = generate({**LOWER_BACK_REHAB, "injury_flags": [], "goals": ["rehab"], "experience_level": "advanced"})
    assert not any(gen.HIGH_IMPACT.search(e.name) for e in exercises_in(plan))


# ---------------------------------------------------------------- the rest of the plan

def test_equipment_is_respected(test_db):
    plan = generate({**LOWER_BACK_REHAB, "injury_flags": [], "goals": ["strength"], "equipment": ["bodyweight"]})
    conn = connect_readonly()
    needs = {r["id"]: set(json.loads(r["equipment_needed"])) for r in conn.execute("SELECT id, equipment_needed FROM exercises")}
    conn.close()
    for e in exercises_in(plan):
        assert needs[e.exercise_id] <= {"none", "chair"}, (e.name, needs[e.exercise_id])
    assert plan.safety.equipment == ["chair", "none"]
    assert gen.available_equipment(["full_gym", "mat"]) is None


def test_sets_reps_rest_come_from_the_protocol_and_fit_the_session(test_db):
    plan = generate(LOWER_BACK_REHAB)
    p = plan.protocol
    assert (p.sets_range, p.reps_range, p.rest_seconds, p.session_length_minutes) == ("1-2", "12-15", 60, 20)
    for d in plan.days:
        assert d.est_minutes <= p.session_length_minutes
        for e in d.exercises:
            assert e.sets == "1-2" and e.rest_seconds == 60
            assert e.reps in ("12-15", "24-30s hold")
    assert p.status == "placeholder" and p.review_notice == "Content pending expert review" and p.citations == []


def test_users_shorter_session_wins(test_db):
    plan = generate({**LOWER_BACK_REHAB, "goals": ["strength"], "injury_flags": [], "session_length_minutes": 15})
    assert plan.protocol.session_length_minutes == 15
    assert all(d.est_minutes <= 15 or len(d.exercises) <= gen.MIN_EXERCISES for d in plan.days)


def test_same_profile_same_plan(test_db):
    assert generate(LOWER_BACK_REHAB).model_dump() == generate(LOWER_BACK_REHAB).model_dump()


@pytest.mark.parametrize("status", ["pregnant", "postpartum"])
def test_pregnant_or_postpartum_gets_no_plan(test_db, search_spy, status):
    plan = generate({**LOWER_BACK_REHAB, "pregnancy_status": status})
    assert plan.generated is False and plan.needs_clinical_review is True
    assert "OB-GYN" in plan.blocked_reason and plan.training_days == 0
    assert all(d.kind == "rest" and not d.exercises for d in plan.days)
    assert search_spy == []                    # it didn't even look for exercises


def test_missing_answers_use_safe_defaults(test_db):
    plan = generate({"goals": [], "injury_flags": [], "equipment": []})
    assert plan.generated and plan.goals == ["general_health"] and plan.experience_level == "beginner"
    assert any("Retake the quiz" in n for n in plan.notes)


# ---------------------------------------------------------------- the protocol content itself

def test_seeded_protocols_cover_every_goal_and_level():
    conn = sqlite3.connect(config.ORIGINAL_DB)
    rows = conn.execute("SELECT goal, experience_level, status, citations FROM goal_protocols").fetchall()
    conn.close()
    assert len(rows) == 15 and {(g, e) for g, e, *_ in rows} == {(g, e) for g in gen.GOALS
                                                                for e in ("beginner", "intermediate", "advanced")}
    assert all(s == "placeholder" and c == "[]" for *_, s, c in rows)


def test_seed_rejects_a_missing_protocol(tmp_path, monkeypatch):
    from app.db import seed
    (tmp_path / "protocols").mkdir()
    (tmp_path / "protocols" / "goal_protocols.yaml").write_text(
        "protocols:\n  - {goal: tone, experience_level: beginner, sessions_per_week: 3, session_length_minutes: 30,"
        " split_type: full_body, sets_range: '2-3', reps_range: '10-12', rest_seconds: 60, progression_note: x}\n",
        encoding="utf-8")
    monkeypatch.setattr(seed, "CONTENT_DIR", tmp_path)
    monkeypatch.setattr(seed, "PROJECT_ROOT", tmp_path)
    conn = sqlite3.connect(":memory:")
    conn.executescript((config.DB_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.execute("INSERT INTO sources VALUES ('placeholder-authored', 0, 'p', NULL, 'x', 'x', 'placeholder')")
    errors: list[str] = []
    seed.seed_goal_protocols(conn, {"placeholder-authored"}, errors)
    assert errors and "missing protocols" in errors[0] and "strength/advanced" in errors[0]


# ---------------------------------------------------------------- the public worked example

def test_worked_example_is_a_live_run_of_the_generator(client, search_spy):
    r = client.get("/api/plan/example")                       # public: no sign-in needed
    assert r.status_code == 200
    ex = r.json()
    assert ex["profile"] == gen.EXAMPLE_PROFILE
    assert ex["profile"]["age"] == 45 and ex["profile"]["injury_flags"] == ["lower_back"]
    assert ex["profile"]["equipment"] == ["resistance_band"] and ex["profile"]["experience_level"] == "beginner"
    assert ex["plan"] == generate(gen.EXAMPLE_PROFILE).model_dump()      # not hand-written: same as the generator
    assert ex["plan"]["safety"]["checked_only"] is True
    assert any(d["kind"] == "rest" for d in ex["plan"]["days"])
    picks = [c for c in search_spy if c.get("muscle_group")]   # the generator's picks (not the funnel's counts)
    assert picks and all(c["checked_only"] is True for c in picks)    # the strict filter ran for the example too


def test_worked_example_funnel_matches_the_filter(client):
    from app.mcp_server.search import search_exercises
    funnel = client.get("/api/plan/example").json()["funnel"]
    counts = [s["exercises_left"] for s in funnel]
    assert counts == sorted(counts, reverse=True) and counts[0] == 903
    flags, eq = ["lower_back"], gen.available_equipment(["resistance_band"])
    assert counts[1] == search_exercises(limit=1, injury_flags=flags)["total_matching"]
    assert counts[2] == search_exercises(limit=1, injury_flags=flags, checked_only=True)["total_matching"]
    assert counts[3] == search_exercises(limit=1, injury_flags=flags, checked_only=True, equipment=eq)["total_matching"]
    assert all(s["removed"] == a["exercises_left"] - s["exercises_left"] for a, s in zip(funnel, funnel[1:]))


def test_worked_example_follows_changes_in_the_data(client):
    before = client.get("/api/plan/example").json()["funnel"][1]["removed"]
    conn = sqlite3.connect(config.WORKING_DB)
    with conn:   # a PT tags one more exercise as unsafe for lower backs
        conn.execute("UPDATE exercises SET injury_contraindications = '[\"lower_back\"]' WHERE id = 'band_pull_apart'")
    conn.close()
    after = client.get("/api/plan/example").json()
    assert after["funnel"][1]["removed"] == before + 1
    assert "band_pull_apart" not in {e["exercise_id"] for d in after["plan"]["days"] for e in d["exercises"]}


# ---------------------------------------------------------------- push / pull days (exercises.force)

PPL = {"goals": ["strength"], "experience_level": "advanced", "days_available": 6, "session_length_minutes": 45,
       "equipment": ["bodyweight", "mat", "resistance_band", "dumbbells"], "other_activity_days": 0,
       "pregnancy_status": "none"}


def forces() -> dict[str, str | None]:
    conn = connect_readonly()
    try:
        return {r["id"]: r["force"] for r in conn.execute("SELECT id, force FROM exercises")}
    finally:
        conn.close()


@pytest.mark.parametrize("flags", [["lower_back"], [], ["shoulder", "wrist"]])
@pytest.mark.parametrize("equipment", [PPL["equipment"], ["bodyweight"], ["bodyweight", "dumbbells", "kettlebells"]])
def test_push_days_never_pull_and_pull_days_never_push(test_db, flags, equipment):
    plan = generate({**PPL, "injury_flags": flags, "equipment": equipment})
    assert plan.protocol.split_type == "push_pull_legs"
    force = forces()
    for day in plan.days:
        if day.focus not in ("Push", "Pull"):
            continue
        opposite = "pull" if day.focus == "Push" else "push"
        for e in day.exercises:
            if e.muscle_group in gen.DIRECTIONAL_GROUPS:
                assert force[e.exercise_id] != opposite, (day.focus, e.name, force[e.exercise_id])


def test_the_reported_pull_day_no_longer_gets_push_ups_or_dips(test_db):
    """Bug 2026-10-22: Pull days included Incline Push-Up and Chair Triceps Dip (filed under "arms")."""
    plan = generate({**PPL, "injury_flags": ["lower_back"]})
    pull = [e.exercise_id for d in plan.days if d.focus == "Pull" for e in d.exercises]
    push = [e.exercise_id for d in plan.days if d.focus == "Push" for e in d.exercises]
    assert pull and not {"incline_pushup", "knee_pushup", "chair_triceps_dip"} & set(pull)
    assert {"incline_pushup", "chair_triceps_dip"} <= set(push)          # they belong on Push days


def test_hand_authored_directions_match_the_movement(test_db):
    f = forces()
    assert {f[i] for i in ("incline_pushup", "knee_pushup", "chair_triceps_dip", "bodyweight_squat")} == {"push"}
    assert {f[i] for i in ("dumbbell_bicep_curl", "band_biceps_curl", "band_seated_row", "band_pull_apart",
                           "dumbbell_bent_over_row")} == {"pull"}


def test_other_splits_are_unaffected(test_db):
    """Only Push/Pull days filter by direction: a full-body day can still mix push and pull moves."""
    plan = generate({**PPL, "goals": ["general_health"], "experience_level": "beginner", "days_available": 3,
                     "injury_flags": []})
    assert plan.protocol.split_type != "push_pull_legs"
    f = forces()
    upper = {f[e.exercise_id] for d in plan.days for e in d.exercises if e.muscle_group in gen.DIRECTIONAL_GROUPS}
    assert {"push", "pull"} <= upper

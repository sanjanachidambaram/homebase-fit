"""The plan generator (app/services/program_generator.py), rewritten 2026-10-25: one goal, a fixed 4-day week by goal,
a repeating 2/4/8-week block, slot-based days with backbone moves, default starting weights and the goal's weight rules.
Plain code, no AI. The injury filter is the same tested SQL as the MCP tool, applied on top of every goal.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_program_generator.py -v
"""

import json
import re
import sqlite3

import pytest

from app import config
from app.db import connect_readonly
from app.safety_rules import INJURY_FLAGS
from app.services import program_generator as gen
from app.services.program_generator import (BLOCK_WEEKS, DEFAULT_WEIGHT_LB, NEEDS_BAR, generate, suggested_weight,
                                            variant_of, weight_steps)

# The profile most tests share: losing weight, a beginner with a lower-back injury, bodyweight + mat + band.
LOWER_BACK_REHAB = {
    "goal": "lose_weight", "injury_flags": ["lower_back"], "experience_level": "beginner",
    "equipment": ["bodyweight", "mat", "resistance_band"], "pregnancy_status": "none",
}
HOME = ["bodyweight", "dumbbells", "mat", "resistance_band"]
UPPER_GROUPS = {"chest", "back", "shoulders", "arms"}


def profile(goal, experience="intermediate", equipment=HOME, flags=()):
    return {"goal": goal, "experience_level": experience, "equipment": list(equipment),
            "injury_flags": list(flags), "pregnancy_status": "none"}


@pytest.fixture
def search_spy(monkeypatch):
    """Records every exercise search the generator makes (it must use the shared, tested filter)."""
    calls = []
    real = gen.search_all_exercises

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)
    monkeypatch.setattr(gen, "search_all_exercises", spy)
    return calls


def contraindications() -> dict[str, tuple[set[str], str]]:
    conn = connect_readonly()
    try:
        return {r["id"]: (set(json.loads(r["injury_contraindications"])), r["contraindication_status"])
                for r in conn.execute("SELECT id, injury_contraindications, contraindication_status FROM exercises")}
    finally:
        conn.close()


def training(plan, week=None):
    weeks = plan.weeks if week is None else [plan.weeks[week]]
    return [d for w in weeks for d in w.days if d.kind == "training"]


def exercises_in(plan):
    return [x for d in training(plan) for x in d.exercises]


# ================================================================ 1. the week, by goal

@pytest.mark.parametrize("goal, counts, block", [
    ("stronger", {"upper": 2, "lower": 1, "cardio": 1}, 2),    # week 1; week 2 swaps upper and lower (below)
    ("lose_weight", {"upper": 1, "lower": 1, "cardio": 2}, 4),
    ("feel_good", {"mobility": 2, "upper": 1, "cardio": 1}, 8),
])
def test_every_goal_has_four_training_days_in_its_own_pattern(test_db, goal, counts, block):
    plan = generate(profile(goal))
    assert plan.generated and plan.training_days == 4 and plan.block_weeks == block == BLOCK_WEEKS[goal]
    assert len(plan.weeks) == block and plan.days == plan.weeks[0].days
    for w in plan.weeks:
        days = [d for d in w.days if d.kind == "training"]
        assert len(days) == 4 and len(w.days) == 7
    week1 = {}
    for d in training(plan, 0):
        week1[d.category] = week1.get(d.category, 0) + 1
    assert week1 == counts


def test_getting_stronger_is_three_strength_days_and_one_cardio_every_week(test_db):
    plan = generate(profile("stronger"))
    for w in range(2):
        cats = sorted(d.category for d in training(plan, w))
        assert cats.count("cardio") == 1 and len([c for c in cats if c in ("upper", "lower")]) == 3
    # odd weeks Upper/Lower/Upper, even weeks Lower/Upper/Lower: each strength day is one OR the other
    assert [d.category for d in training(plan, 0)][:3] == ["upper", "lower", "upper"]
    assert [d.category for d in training(plan, 1)][:3] == ["lower", "upper", "lower"]


def test_feeling_good_is_two_mobility_one_strength_one_cardio_for_all_eight_weeks(test_db):
    plan = generate(profile("feel_good"))
    for w in range(8):
        cats = sorted(d.category for d in training(plan, w))
        assert cats.count("mobility") == 2 and cats.count("cardio") == 1
        assert len([c for c in cats if c in ("upper", "lower")]) == 1


def test_upper_and_lower_are_never_mixed_on_a_day(test_db):
    for goal in gen.GOALS:
        for d in training(generate(profile(goal))):
            groups = {x.muscle_group for x in d.exercises}
            if d.category == "upper":
                assert groups <= UPPER_GROUPS, (goal, d.day, groups)
            elif d.category == "lower":
                assert groups == {"legs"}, (goal, d.day, groups)


# ================================================================ 2. the repeating weeks

def test_the_same_exercises_come_back_on_odd_weeks_and_on_even_weeks():
    """Week 1 = week 3 = week 5 (variant 0); week 2 = week 4 (variant 1). The calendar maps dates the same way."""
    assert [variant_of(w, 2) for w in range(1, 7)] == [0, 1, 0, 1, 0, 1]
    assert [variant_of(w, 4) for w in range(1, 10)] == [0, 1, 2, 3, 0, 1, 2, 3, 0]     # weeks 5-8 repeat 1-4
    assert [variant_of(w, 8) for w in (1, 8, 9, 16, 17)] == [0, 7, 0, 7, 0]           # weeks 9-16 repeat 1-8


def test_weeks_in_a_block_differ_where_the_pool_allows(test_db):
    plan = generate(profile("lose_weight", "advanced", equipment=["full_gym"]))
    uppers = [tuple(x.exercise_id for x in next(d for d in training(plan, w) if d.category == "upper").exercises)
              for w in range(4)]
    assert len(set(uppers)) == 4                                                      # 4 different upper days


def test_same_profile_same_plan(test_db):
    assert generate(LOWER_BACK_REHAB) == generate(LOWER_BACK_REHAB)


# ================================================================ 3. what goes into a day

def test_every_strength_day_hits_two_muscle_groups_plus_two_accessories(test_db):
    for goal in gen.GOALS:
        for exp in gen.EXPERIENCE:
            for eq in (["bodyweight"], HOME, ["full_gym"]):
                plan = generate(profile(goal, exp, eq))
                for d in training(plan):
                    if d.category not in ("upper", "lower"):
                        continue
                    accessories = [x for x in d.exercises if "accessory" in x.slot or x.slot in ("shoulders", "arms")]
                    assert len(accessories) >= 2, (goal, exp, eq, d.day, [x.slot for x in d.exercises])
                    if d.category == "upper":
                        assert len({x.muscle_group for x in d.exercises}) >= 2, (goal, exp, eq, d.day)
                    else:   # lower: a knee-dominant and a hip-dominant move (quads AND glutes/hamstrings)
                        assert {"knee", "hip"} <= {x.slot for x in d.exercises}, (goal, exp, eq, d.day)


def test_backbone_moves_come_first(test_db):
    """The "most effective, easiest at home" lists, matched against the real library (never invented)."""
    plan = generate(profile("lose_weight", "beginner", ["bodyweight", "mat"]))
    names = lambda cat: " ".join(x.name.lower() for d in training(plan) if d.category == cat for x in d.exercises)  # noqa: E731
    assert re.search(r"push-?up", names("upper")) and re.search(r"squat", names("lower"))
    assert re.search(r"bridge|butt lift", names("lower"))
    assert re.search(r"march|step jack", names("cardio"))                            # low-impact options for beginners
    fg = generate(profile("feel_good", "beginner", ["bodyweight", "mat"]))
    mobility = " ".join(x.name.lower() for d in training(fg) if d.category == "mobility" for x in d.exercises)
    assert re.search(r"plank|dead bug", mobility) and re.search(r"bird dog|cat", mobility)


def test_days_are_15_to_60_minutes_and_never_over_the_session_length(test_db):
    for goal in gen.GOALS:
        for exp in gen.EXPERIENCE:
            plan = generate(profile(goal, exp))
            for d in training(plan):
                assert 15 <= d.est_minutes <= 60, (goal, exp, d.day, d.category, d.est_minutes)
                assert d.est_minutes <= plan.protocol.session_length_minutes, (goal, exp, d.day, d.est_minutes)


def test_no_day_repeats_a_near_duplicate_move(test_db):
    # e.g. a knee injury empties the squat/lunge slots: the fallbacks mustn't fill a day with three calf raises
    for prof in (profile("stronger", "intermediate", ["bodyweight", "dumbbells", "kettlebells"], ["knee"]),
                 profile("lose_weight", "advanced"), profile("feel_good", "beginner", flags=["hip"])):
        for d in training(generate(prof)):
            for family in gen.ONE_PER_DAY:
                assert sum(bool(family.search(x.name)) for x in d.exercises) <= 1, (d.day, [x.name for x in d.exercises])


def test_sets_reps_and_rest_come_from_the_protocol(test_db):
    plan = generate(profile("stronger", "intermediate"))
    p = plan.protocol
    assert (p.sets_range, p.reps_range, p.rest_seconds, p.session_length_minutes) == ("3", "6-10", 120, 45)
    for x in exercises_in(plan):
        if x.category in ("upper", "lower"):
            assert x.sets == "3" and x.rest_seconds == 120
            assert x.reps_your_call is not ("hold" in x.reps)                       # stronger: reps are your call


def test_no_jumping_for_beginners_or_injuries_and_no_bar_moves_without_a_gym(test_db):
    for prof in (profile("stronger", "beginner"), {**profile("stronger", "advanced"), "injury_flags": ["knee"]},
                 profile("stronger", "intermediate", ["bodyweight", "dumbbells", "kettlebells"], ["knee"])):
        names = [x.name for x in exercises_in(generate(prof))]
        assert not any(gen.HIGH_IMPACT.search(n) for n in names), names    # incl. cleans, snatches, jerks, thrusters
    assert not any(NEEDS_BAR.search(x.name) for x in exercises_in(generate(profile("stronger", "advanced", HOME))))


def test_equipment_is_respected(test_db):
    plan = generate(profile("stronger", "advanced", ["bodyweight"]))
    conn = connect_readonly()
    eq = {r["id"]: set(json.loads(r["equipment_needed"])) for r in conn.execute("SELECT id, equipment_needed FROM exercises")}
    conn.close()
    for x in exercises_in(plan):
        assert eq[x.exercise_id] <= {"none", "chair"}, x.name
        assert x.weighted is False and x.default_weight_lb is None                     # nothing to put a weight on


# ================================================================ 4. weights (shared_rules.md rule 8)

def test_default_starting_weights_by_experience(test_db):
    assert DEFAULT_WEIGHT_LB == {"beginner": None, "intermediate": {"arms": 10, "legs": 20},
                                 "advanced": {"arms": 20, "legs": 40}}
    for exp, arms, legs in (("beginner", None, None), ("intermediate", 10, 20), ("advanced", 20, 40)):
        plan = generate(profile("stronger", exp, HOME))
        weighted = [x for x in exercises_in(plan) if x.weighted]
        assert weighted, exp
        for x in weighted:
            assert x.default_weight_lb == (arms if x.load == "arms" else legs), (exp, x.name)
            assert x.load == ("arms" if x.category == "upper" else "legs")


def test_bodyweight_moves_never_get_a_weight(test_db):
    for x in exercises_in(generate(profile("stronger", "advanced", HOME))):
        if not x.weighted:
            assert x.default_weight_lb is None and x.load is None


def test_getting_stronger_adds_weight_each_time_a_day_comes_round():
    # an exercise on odd weeks (variant 0): weeks 1, 3, 5... From a 10 lb start in week 1:
    steps = [weight_steps("stronger", 2, {0}, 1, w) for w in (1, 3, 5, 7)]
    assert steps == [0, 1, 2, 3]
    assert [suggested_weight("stronger", "arms", 10, s) for s in steps] == [10, 12.5, 15, 17.5]   # +2.5 lb arms
    assert [suggested_weight("stronger", "legs", 20, s) for s in steps] == [20, 25, 30, 35]       # +5 lb legs
    assert weight_steps("stronger", 2, {0, 1}, 1, 4) == 3                       # on both patterns: every week


def test_losing_weight_adds_5_lb_every_4_weeks():
    weights = [suggested_weight("lose_weight", "arms", 10, weight_steps("lose_weight", 4, {0}, 1, w))
               for w in (1, 4, 5, 8, 9, 12, 13)]
    assert weights == [10, 10, 15, 15, 20, 20, 25]                              # weeks 5-8 repeat 1-4, 5 lb heavier


def test_feeling_good_never_raises_a_weight():
    assert all(weight_steps("feel_good", 8, {0}, 1, w) == 0 for w in range(1, 30))
    assert suggested_weight("feel_good", "legs", 22.5, 0) == 22.5


def test_weights_build_on_a_logged_anchor_not_just_the_default():
    """Calibration: a weight logged in week 3 becomes the new anchor; increases count from there."""
    assert weight_steps("stronger", 2, {0}, 3, 7) == 2 and suggested_weight("stronger", "arms", 15, 2) == 20
    assert suggested_weight("stronger", "arms", None, 5) is None                # no anchor (beginner, nothing logged)


def test_the_plan_shows_the_weight_schedule(test_db):
    plan = generate(profile("lose_weight", "intermediate", HOME))
    w = plan.weights
    assert w.schedule_weeks == 8 and w.defaults_lb == {"arms": 10, "legs": 20} and "5 lb every 4 weeks" in w.rule
    row = w.schedule[0]
    assert row.weight_lb == [row.weight_lb[0]] * len([wk for wk in row.weeks if wk <= 4]) + \
        [row.weight_lb[0] + 5] * len([wk for wk in row.weeks if wk > 4])


# ================================================================ 5. safety: unchanged, on top of every goal

def test_injury_filter_is_applied_during_generation(test_db, search_spy):
    plan = generate(LOWER_BACK_REHAB)
    assert plan.generated and search_spy, "the generator must use the shared exercise search"
    assert all(c["checked_only"] is True and c["injury_flags"] == ["lower_back"] for c in search_spy)
    tags = contraindications()
    for x in exercises_in(plan):
        unsafe, status = tags[x.exercise_id]
        assert "lower_back" not in unsafe and status != "untagged", x.name
    assert plan.safety.checked_only is True and plan.safety.excluded_as_contraindicated > 0


@pytest.mark.parametrize("goal", gen.GOALS)
def test_every_injury_flag_filters_every_goal(test_db, search_spy, goal):
    tags = contraindications()
    for flag in INJURY_FLAGS:
        search_spy.clear()
        plan = generate(profile(goal, flags=[flag]))
        assert search_spy and all(c["checked_only"] is True and c["injury_flags"] == [flag] for c in search_spy)
        assert all(flag not in tags[x.exercise_id][0] for x in exercises_in(plan)), (goal, flag)


def test_a_newly_tagged_exercise_is_excluded_too(test_db):
    before = {x.exercise_id for x in exercises_in(generate(LOWER_BACK_REHAB))}
    assert "glute_bridge" in before
    conn = sqlite3.connect(config.WORKING_DB)
    with conn:
        conn.execute("UPDATE exercises SET injury_contraindications = '[\"lower_back\"]' WHERE id = 'glute_bridge'")
    conn.close()
    assert "glute_bridge" not in {x.exercise_id for x in exercises_in(generate(LOWER_BACK_REHAB))}


def test_no_injury_means_no_checked_only(test_db, search_spy):
    plan = generate(profile("stronger"))
    assert all(c["checked_only"] is False for c in search_spy) and plan.safety.checked_only is False


@pytest.mark.parametrize("status", ["pregnant", "postpartum"])
def test_pregnant_or_postpartum_gets_no_plan(test_db, search_spy, status):
    plan = generate({**LOWER_BACK_REHAB, "pregnancy_status": status})
    assert not plan.generated and plan.needs_clinical_review and search_spy == []
    assert all(d.kind == "rest" for d in plan.days)


# ================================================================ 6. the protocol content

def test_seeded_protocols_cover_every_goal_and_level():
    conn = sqlite3.connect(config.ORIGINAL_DB)
    rows = conn.execute("SELECT goal, experience_level, session_length_minutes, status, citations "
                        "FROM goal_protocols").fetchall()
    conn.close()
    assert len(rows) == 9 and {(g, e) for g, e, *_ in rows} == {(g, e) for g in gen.GOALS for e in gen.EXPERIENCE}
    assert all(15 <= m <= 60 and s == "placeholder" and c == "[]" for *_, m, s, c in rows)


def test_seed_rejects_a_missing_protocol(tmp_path, monkeypatch):
    from app.db import seed
    (tmp_path / "protocols").mkdir()
    (tmp_path / "protocols" / "goal_protocols.yaml").write_text(
        "protocols:\n  - {goal: stronger, experience_level: beginner, session_length_minutes: 40,"
        " sets_range: '2-3', reps_range: '8-12', rest_seconds: 90, progression_note: x}\n", encoding="utf-8")
    monkeypatch.setattr(seed, "CONTENT_DIR", tmp_path)
    monkeypatch.setattr(seed, "PROJECT_ROOT", tmp_path)
    conn = sqlite3.connect(":memory:")
    conn.executescript((config.DB_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.execute("INSERT INTO sources VALUES ('placeholder-authored', 0, 'p', NULL, 'x', 'x', 'placeholder')")
    errors: list[str] = []
    seed.seed_goal_protocols(conn, {"placeholder-authored"}, errors)
    assert errors and "missing protocols" in errors[0] and "feel_good/advanced" in errors[0]


# ================================================================ 7. review-mode swaps and the worked example

def test_swaps_only_from_the_same_slot_and_filters(test_db):
    plan = generate(LOWER_BACK_REHAB, with_swap_options=True)
    original, options = next((k, v) for k, v in plan.swap_options.items() if v)
    tags = contraindications()
    assert all("lower_back" not in tags[o["id"]][0] for opts in plan.swap_options.values() for o in opts)
    swapped = generate(LOWER_BACK_REHAB, swaps={original: options[0]["id"]})
    ids = {x.exercise_id for x in exercises_in(swapped)}
    assert options[0]["id"] in ids and original not in ids
    assert generate(LOWER_BACK_REHAB, swaps={original: "superman_hold"}) == generate(LOWER_BACK_REHAB)   # unsafe: ignored


def test_worked_example_is_a_live_run_of_the_generator(client, search_spy):
    r = client.get("/api/plan/example")                       # public: no sign-in needed
    assert r.status_code == 200
    ex = r.json()
    assert ex["profile"] == gen.EXAMPLE_PROFILE
    assert ex["profile"]["goal"] == "feel_good" and ex["profile"]["injury_flags"] == ["lower_back"]
    assert ex["plan"] == generate(gen.EXAMPLE_PROFILE).model_dump()      # not hand-written: same as the generator
    assert ex["plan"]["safety"]["checked_only"] is True and ex["plan"]["block_weeks"] == 8
    picks = [c for c in search_spy if c.get("muscle_group")]
    assert picks and all(c["checked_only"] is True for c in picks)


def test_worked_example_funnel_matches_the_filter(client):
    from app.mcp_server.search import search_all_exercises
    funnel = client.get("/api/plan/example").json()["funnel"]
    counts = [s["exercises_left"] for s in funnel]
    assert counts == sorted(counts, reverse=True) and counts[0] == 903
    flags, eq = ["lower_back"], gen.available_equipment(gen.EXAMPLE_PROFILE["equipment"])
    assert counts[1] == search_all_exercises(injury_flags=flags)["total_matching"]
    assert counts[2] == search_all_exercises(injury_flags=flags, checked_only=True)["total_matching"]
    assert counts[3] == search_all_exercises(injury_flags=flags, checked_only=True, equipment=eq)["total_matching"]
    assert all(s["removed"] == a["exercises_left"] - s["exercises_left"] for a, s in zip(funnel, funnel[1:]))

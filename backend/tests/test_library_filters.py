"""The Exercise Library's filters (rewritten 2026-10-25) and the Dashboard's streak card.

The library now filters like the quiz reads: a workout group to focus on (upper | lower | mobility_core, the plans'
own groups) and body areas to avoid because of an injury (the quiz's flags). The level and injury-status filters are
gone. These tests check that avoiding an area really leaves out every exercise tagged for it AND every untagged one,
that it is literally the same safety search the plan generator and the MCP tool use, and that removing the old
filters loosened nothing anywhere else.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_library_filters.py -v
"""

from datetime import timedelta

import pytest

from app.db import connect
from app.mcp_server.search import search_all_exercises, search_exercises
from app.safety_rules import INJURY_FLAGS, checked_only_for
from app.services.program_generator import generate
from app.services.workout_review import workout_groups
from tests.test_calendar import MONDAY, account, on_day  # noqa: F401  (on_day is a fixture)
from tests.test_injury_rationale import library
from tests.test_mcp_tools import tag
from tests.test_program_generator import profile


def ids(items) -> set[str]:
    return {e["id"] for e in items}


# ---------------------------------------------------------------- avoiding body areas (the injury exclusion)

@pytest.mark.parametrize("flag", INJURY_FLAGS)
def test_avoiding_an_area_leaves_out_tagged_and_untagged_exercises(client, flag):
    everything = library(client)
    kept = library(client, avoid=flag)
    assert kept and len(kept) < len(everything)
    for e in kept:
        assert flag not in e["injury_contraindications"], e["id"]              # tagged risky for it: gone
        assert e["contraindication_status"] != "untagged", e["id"]             # never checked: never assumed safe
    # and nothing safe was dropped: every checked exercise without that tag is still there
    want = {e["id"] for e in everything if flag not in e["injury_contraindications"]
            and e["contraindication_status"] != "untagged"}
    assert ids(kept) == want


def test_avoiding_several_areas_leaves_out_any_of_them(client):
    kept = library(client, avoid=["shoulder", "knee", "lower_back"])
    assert kept and not any({"shoulder", "knee", "lower_back"} & set(e["injury_contraindications"]) for e in kept)
    assert ids(kept) <= ids(library(client, avoid="shoulder")) & ids(library(client, avoid="knee"))


def test_avoid_is_the_same_search_the_plan_generator_uses(client):
    """Not a second, library-only check: the same function, with checked_only forced on for any flag."""
    for flags in (["shoulder"], ["knee", "wrist"], list(INJURY_FLAGS)):
        shared = search_all_exercises(injury_flags=flags, checked_only=checked_only_for(flags))["exercises"]
        assert ids(library(client, avoid=flags)) == ids(shared)


def test_a_newly_tagged_exercise_drops_out_of_the_library_too(client, test_db):
    assert "band_biceps_curl" in ids(library(client, avoid="wrist"))         # checked, no cautions drafted
    tag("band_biceps_curl", ["wrist"])
    assert "band_biceps_curl" not in ids(library(client, avoid="wrist"))
    assert "band_biceps_curl" in ids(library(client, avoid="knee"))            # only for the area it's tagged for


def test_unknown_areas_and_groups_are_rejected(client):
    for params in ({"avoid": "elbow"}, {"avoid": "none"}, {"group": "arms"}, {"group": "cardio"}, {"equipment": "jetpack"}):
        assert client.get("/api/exercises", params=params).status_code == 422, params


# ---------------------------------------------------------------- the three workout groups

def test_the_focus_filter_has_exactly_the_plans_three_groups(client):
    everything = library(client)
    for group in ("upper", "lower", "mobility_core"):
        got = library(client, group=group)
        assert got and all(group in e["workout_groups"] for e in got)
        assert ids(got) == {e["id"] for e in everything if group in workout_groups(e)}
    # the Workout Reviewer's sorting, so the library and the reviewer always agree
    assert {g for e in everything for g in e["workout_groups"]} == {"cardio", "upper", "lower", "mobility_core"}
    sample = {e["id"]: e["workout_groups"] for e in everything}
    assert sample["incline_pushup"] == ["upper"] and sample["bodyweight_squat"] == ["lower"]
    assert sample["dead_bug"] == ["mobility_core"] and sample["bird_dog"] == ["mobility_core"]


def test_upper_body_but_not_my_shoulders(client):
    """'I want upper body, but leave out what'll hurt my shoulders.'"""
    got = library(client, group="upper", avoid="shoulder")
    assert got and all("upper" in e["workout_groups"] for e in got)
    assert not any("shoulder" in e["injury_contraindications"] for e in got)
    assert not any(e["contraindication_status"] == "untagged" for e in got)
    assert ids(got) == ids(library(client, group="upper")) & ids(library(client, avoid="shoulder"))


def test_the_old_level_and_injury_status_filters_are_gone(client):
    from app.exercises import list_exercises
    import inspect
    assert set(inspect.signature(list_exercises).parameters) == {"group", "avoid", "source", "equipment", "conn"}


# ---------------------------------------------------------------- nothing loosened anywhere else

def test_the_safety_check_elsewhere_is_unchanged(test_db):
    """Removing the library's level / injury-status filters touched no other safety rule."""
    assert all(checked_only_for([f]) for f in INJURY_FLAGS) and not checked_only_for([])
    for flag in INJURY_FLAGS:
        # the MCP tool the agents use
        r = search_exercises(injury_flags=[flag], checked_only=True, limit=50)
        assert not any(flag in e["injury_contraindications"] or e["injury_check"] == "not_yet_checked"
                       for e in r["exercises"])
        # the plan generator: checked_only forced on, nothing tagged for the flag
        plan = generate(profile("stronger", flags=[flag]))
        assert plan.safety.checked_only is True
        planned = {x.exercise_id for w in plan.weeks for d in w.days for x in d.exercises}
        conn = connect()
        try:
            tagged = {r[0] for r in conn.execute(
                "SELECT e.id FROM exercises e, jsonb_array_elements_text(e.injury_contraindications::jsonb) c(value) WHERE c.value = ?", (flag,))}
            untagged = {r[0] for r in conn.execute(
                "SELECT id FROM exercises WHERE contraindication_status = 'untagged'")}
        finally:
            conn.close()
        assert not planned & tagged and not planned & untagged, flag


# ---------------------------------------------------------------- the Dashboard's streak card

def log_day(uid, d):
    conn = connect()
    with conn:
        conn.execute("INSERT INTO workout_logs (user_id, date, exercise_id, sets, reps) VALUES (?, ?, 'dead_bug', 2, 10)",
                     (uid, d.isoformat()))
    conn.close()


def test_streak_card_counts_current_and_longest_and_badges(client, on_day):
    uid, h = account(client, "streaky")
    today = MONDAY + timedelta(days=20)
    on_day(today)
    for back in (1, 2, 3, 4, 5, 6, 7, 8):                     # an 8-day run that ended 10 days ago
        log_day(uid, today - timedelta(days=9 + back))
    for back in (0, 1, 2):                                   # and a 3-day run up to today
        log_day(uid, today - timedelta(days=back))
    s = client.get("/api/progress/streak", headers=h).json()
    assert (s["current_streak_days"], s["longest_streak_days"], s["active_days_last_30"]) == (3, 8, 11)
    assert s["badges"] == [{"days": 3, "earned": True}, {"days": 7, "earned": True},
                           {"days": 14, "earned": False}, {"days": 30, "earned": False}]
    assert s["next_badge"] == {"days": 7, "to_go": 4} and s["rest_day_suggested"] is False
    assert client.get("/api/progress/streak").status_code == 401


def test_streak_card_for_someone_who_hasnt_started(client, on_day):
    uid, h = account(client, "fresh")
    s = client.get("/api/progress/streak", headers=h).json()
    assert (s["current_streak_days"], s["longest_streak_days"]) == (0, 0)
    assert not any(b["earned"] for b in s["badges"]) and s["next_badge"] == {"days": 3, "to_go": 3}

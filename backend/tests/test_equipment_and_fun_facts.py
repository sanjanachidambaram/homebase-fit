"""The live equipment list (Build Your Own and the library filter) and the strength fun-fact comparisons.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_equipment_and_fun_facts.py -v
"""

import random

import pytest

from app.agents.coach import tone_problems
from app.agents.workout_builder import WorkoutRequest
from app.db import connect
from app.mcp_server.search import _clean_equipment, search_exercises
from app.mcp_server.strength import COMPARISONS, compute_strength_equivalents


def db_equipment() -> set[str]:
    conn = connect()
    try:
        return {r[0] for r in conn.execute("SELECT DISTINCT n.value FROM exercises e, jsonb_array_elements_text(e.equipment_needed::jsonb) n(value)")}
    finally:
        conn.close()


# ---------------------------------------------------------------- equipment: one live list, never hand-typed

def test_equipment_list_is_exactly_what_the_exercises_use(client):
    options = client.get("/api/exercises/equipment").json()
    assert {o["value"] for o in options} == db_equipment()
    assert len(options) == len(db_equipment()) >= 14
    assert options[0] == {**options[0], "value": "none", "label": "Bodyweight", "always_included": True}
    assert all(o["label"] and o["exercises"] > 0 for o in options)
    assert sum(o["always_included"] for o in options) == 1


def test_every_equipment_value_on_any_exercise_is_selectable_in_build_your_own(client):
    """Each value the exercises use is offered by the picker's endpoint AND accepted everywhere a pick goes:
    the Workout Builder request, the builder's exercise search, and the library filter."""
    offered = {o["value"] for o in client.get("/api/exercises/equipment").json()}
    for value in db_equipment():
        assert value in offered, value
        assert WorkoutRequest(picks={"core": 1}, time_budget_minutes=20, equipment=[value]).equipment == [value]
        assert _clean_equipment([value]) == [value]                              # what the builder's search accepts
        found = search_exercises(equipment=[value], limit=50)["exercises"]
        assert found, value                                                      # and it finds exercises with it
        uses = client.get("/api/exercises", params={"equipment": value}).json()
        assert uses and all(value in e["equipment_needed"] for e in uses), value


def test_equipment_list_follows_the_data(client):
    conn = connect()
    with conn:
        conn.execute("""UPDATE exercises SET equipment_needed = '["sandbag"]' WHERE id = '3_4_Sit-Up'""")
    conn.close()
    values = {o["value"] for o in client.get("/api/exercises/equipment").json()}
    assert "sandbag" in values                                                   # new value shows up, no code change
    assert client.get("/api/exercises", params={"equipment": "sandbag"}).status_code == 200
    assert client.get("/api/exercises", params={"equipment": "jetpack"}).status_code == 422


# ---------------------------------------------------------------- the fun facts

BALLPARKS = {   # thing: (low, high) a reasonable adult/typical weight range in pounds
    "chihuahua": (3, 6), "house cat": (8, 11), "bowling ball": (6, 16), "large raccoon": (20, 30),
    "toddler": (24, 30), "golden retriever": (55, 75), "giant panda": (150, 275), "motorcycle": (350, 450),
    "vending machine": (600, 1000), "concert grand piano": (990, 1100), "cow": (1000, 1400),
    "full-size car": (3500, 5000), "full-size tree": (4000, 6000), "adult elephant": (10000, 13500),
    "blue whale": (100000, 330000),
}


def test_every_comparison_is_in_the_right_ballpark_and_listed_in_size_order():
    assert {c["singular"] for c in COMPARISONS} == set(BALLPARKS)
    for c in COMPARISONS:
        lo, hi = BALLPARKS[c["singular"]]
        assert lo <= c["unit_weight_lbs"] <= hi, c["singular"]
        assert c["basis"].strip() and c["source"].strip()
    weights = [c["unit_weight_lbs"] for c in COMPARISONS]
    tiers = [c["tier"] for c in COMPARISONS]
    assert weights == sorted(weights) and tiers == sorted(tiers)


def test_comparisons_are_about_objects_and_animals_never_food_or_bodies():
    """shared_rules.md rule 5: the Coach's tone guard must pass on every name, basis and phrase."""
    for c in COMPARISONS:
        for text in (c["name"], c["singular"], c["basis"]):
            assert not tone_problems(text), (c["key"], text, tone_problems(text))
    for c in compute_strength_equivalents(5000)["comparisons"]:
        assert not tone_problems(c["phrase"]), c["phrase"]
    forbidden = ("milk", "beer", "keg", "pizza", "burger", "cake", "food", "drink", "pound of", "body")
    assert not any(w in c["name"] for c in COMPARISONS for w in forbidden)


def test_tiers_offer_two_or_three_options_except_the_giants():
    sizes = {}
    for c in COMPARISONS:
        sizes.setdefault(c["tier"], []).append(c["singular"])
    for tier, things in sizes.items():
        assert len(things) in ((1,) if tier >= 6 else (2, 3)), (tier, things)   # elephant / blue whale stand alone


@pytest.mark.parametrize("total, expected", [
    (40, {"large raccoons", "toddlers"}),                    # reaches 2 of tier 2 (not a 70 lb golden retriever)
    (75, {"large raccoons", "toddlers", "golden retrievers"}),
    (500, {"giant pandas", "motorcycles"}),
    (2000, {"vending machines", "concert grand pianos", "cows"}),
    (6600, {"full-size cars", "full-size trees"}),
    (25000, {"adult elephants"}),
])
def test_headline_varies_within_the_reached_tier(total, expected):
    r = compute_strength_equivalents(total, random.Random(1))
    assert set(r["headline_options"]) == expected
    seen = {compute_strength_equivalents(total, random.Random(seed))["headline_comparison"] for seed in range(60)}
    assert seen == expected                                  # every option comes up across visits, nothing else
    again = [compute_strength_equivalents(total, random.Random(7))["headline"] for _ in range(3)]
    assert len(set(again)) == 1                              # a seeded pick is repeatable (for tests)


def test_tiny_totals_say_a_fraction_of_a_chihuahua():
    assert compute_strength_equivalents(3)["headline"] == "You've lifted 0.60 of a chihuahua. Keep going!"
    assert compute_strength_equivalents(5)["headline"] == "You've lifted about 1.0 chihuahua!"

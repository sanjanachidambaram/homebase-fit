"""Library filters (real query params) and the reasoning behind every injury tag.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_injury_rationale.py -v

The reasoning is AI-drafted, general exercise science: every entry must say so (tier ai_drafted, source
"Pending review by a licensed physical therapist") until a PT reviews it, and it must never look like a citation.
None of this changes the injury filter itself (see test_program_generator / test_mcp_tools).
"""

import csv
import json
import re

import pytest

from app.config import CONTENT_DIR
from app.db.seed import injury_rationale
from app.safety_rules import RATIONALE_PENDING_SOURCE
from app.services.program_generator import generate
from tests.test_plan_agent import account, explainer  # noqa: F401  (explainer is a fixture)
from tests.test_program_generator import LOWER_BACK_REHAB


def library(client, **params) -> list[dict]:
    r = client.get("/api/exercises", params=params)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- the rationale data

def test_every_injury_tag_has_an_ai_drafted_reason(client):
    tagged = [e for e in library(client) if e["injury_contraindications"]]
    assert len(tagged) == 17 and sum(len(e["injury_contraindications"]) for e in tagged) == 30
    for e in library(client):
        assert set(e["injury_rationale"]) == set(e["injury_contraindications"]), e["id"]
        for injury, r in e["injury_rationale"].items():
            assert set(r) == {"reasoning", "tier", "source"}
            assert r["tier"] == "ai_drafted" and r["source"] == RATIONALE_PENDING_SOURCE
            assert len(r["reasoning"]) > 40
            # general reasoning, never a citation: no years, "et al.", DOIs, journals, or "studies show"
            assert not re.search(r"\b(19|20)\d\d\b|et al|doi|journal|stud(y|ies) (show|found)|research",
                                 r["reasoning"], re.I), (e["id"], injury)


def test_burpee_reasoning_explains_the_lower_back_flag(client):
    burpee = client.get("/api/exercises/burpee").json()
    r = burpee["injury_rationale"]["lower_back"]
    assert "spine" in r["reasoning"] and "jump" in r["reasoning"]


def test_seed_rejects_bad_or_missing_rationale():
    ok = {"reasoning": "Squats bend the knee under load.", "tier": "ai_drafted", "source": RATIONALE_PENDING_SOURCE}
    errors: list[str] = []
    assert injury_rationale({"injury_rationale": {"knee": ok}}, ["knee"], "x", errors) == {"knee": ok} and not errors

    cases = [
        ({}, ["knee"]),                                                           # tag with no reason
        ({"injury_rationale": {"knee": ok}}, []),                                 # reason with no tag
        ({"injury_rationale": {"knee": {**ok, "tier": "guess"}}}, ["knee"]),
        ({"injury_rationale": {"knee": {**ok, "tier": "pt_reviewed"}}}, ["knee"]),  # reviewed, but no reviewer named
        ({"injury_rationale": {"knee": {**ok, "source": "Smith et al. 2019"}}}, ["knee"]),  # drafted must say pending
        ({"injury_rationale": {"knee": {"reasoning": "x", "tier": "ai_drafted"}}}, ["knee"]),
    ]
    for ex, tags in cases:
        errors = []
        injury_rationale(ex, tags, "x", errors)
        assert errors, (ex, tags)

    errors = []
    reviewed = {**ok, "tier": "pt_reviewed", "source": "Jane Doe, PT, DPT"}
    assert injury_rationale({"injury_rationale": {"knee": reviewed}}, ["knee"], "x", errors)["knee"] == reviewed
    assert not errors


def test_pt_template_has_the_rationale_for_review():
    path = CONTENT_DIR / "exercises" / "contraindication_tags_TEMPLATE.csv"
    rows = {r["exercise_id"]: r for r in csv.DictReader(path.open(encoding="utf-8-sig"))}
    assert {"rationale", "rationale_tier", "reviewed_by"} <= set(next(iter(rows.values())))
    climber = rows["mountain_climber"]
    assert climber["rationale"].splitlines()[0].startswith("lower_back: ") and climber["rationale_tier"] == "ai_drafted"
    assert rows["dead_bug"]["rationale"] == "" and rows["3_4_Sit-Up"]["rationale"] == ""


# ---------------------------------------------------------------- filters (in SQL, via query params)

def test_equipment_filter_matches_what_an_exercise_uses(client):
    bands = library(client, equipment="resistance_band")
    assert bands and all("resistance_band" in e["equipment_needed"] for e in bands)
    both = library(client, equipment=["resistance_band", "mat"])
    assert len(both) > len(bands)
    assert all({"resistance_band", "mat"} & set(e["equipment_needed"]) for e in both)


def test_level_and_injury_status_filters(client):
    beginners = library(client, difficulty="beginner")
    assert beginners and {e["difficulty"] for e in beginners} == {"beginner"}
    two = library(client, difficulty=["beginner", "advanced"])
    assert {e["difficulty"] for e in two} == {"beginner", "advanced"}

    drafted = library(client, injury_status="draft")
    assert {e["contraindication_status"] for e in drafted} == {"draft"} and len(drafted) == 27
    untagged = library(client, injury_status="untagged")
    assert {e["contraindication_status"] for e in untagged} == {"untagged"}
    assert len(drafted) + len(untagged) == len(library(client))
    assert library(client, injury_status="pt_reviewed") == []          # nobody has reviewed anything yet


def test_filters_combine(client):
    got = library(client, muscle_group="legs", equipment="none", difficulty="beginner", injury_status="draft")
    assert {e["id"] for e in got} == {"bodyweight_squat", "reverse_lunge", "wall_sit"}


@pytest.mark.parametrize("params", [{"equipment": "jetpack"}, {"difficulty": "expert"}, {"injury_status": "safe"}])
def test_unknown_filter_values_are_rejected(client, params):
    assert client.get("/api/exercises", params=params).status_code == 422


# ---------------------------------------------------------------- the plan says what it left out, and why

def test_plan_lists_what_the_injury_filter_left_out(test_db):
    plan = generate(LOWER_BACK_REHAB)
    left_out = plan.safety.left_out_for_injury
    assert len(left_out) == plan.safety.excluded_as_contraindicated > 0
    planned = {e.exercise_id for d in plan.days for e in d.exercises}
    for x in left_out:
        assert x.exercise_id not in planned
        assert [c.injury for c in x.cautions] == ["lower_back"]          # only the user's own flag
        assert x.cautions[0].reasoning and x.cautions[0].tier == "ai_drafted"
    # every hand-authored exercise tagged lower_back that fits mat / band / bodyweight in this plan's groups
    assert {x.exercise_id for x in left_out} == {"burpee", "crunch", "mountain_climber", "superman_hold"}


def test_no_injury_means_nothing_left_out(test_db):
    plan = generate({**LOWER_BACK_REHAB, "injury_flags": []})
    assert plan.safety.left_out_for_injury == [] and plan.safety.excluded_as_contraindicated == 0


def test_the_model_never_sees_the_injury_reasoning(client, explainer):
    e = explainer("Here's why it fits.")
    uid, h = account(client, email="reasons@example.com")
    res = client.post("/api/programs/recommend", headers=h).json()
    left_out = res["result"]["plan"]["safety"]["left_out_for_injury"]
    assert left_out, "the person sees what was left out and why"
    shown = " ".join(e.prompts)
    for x in left_out:
        assert x["name"] not in shown
        for c in x["cautions"]:
            assert c["reasoning"] not in shown
    assert "lower_back" not in shown and "left_out" not in shown and json.dumps(RATIONALE_PENDING_SOURCE)[1:-1] not in shown

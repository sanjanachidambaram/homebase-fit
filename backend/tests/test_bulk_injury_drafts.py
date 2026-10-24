"""The one-time AI drafting of injury cautions for the imported library (app/db/draft_injury_tags.py).

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_bulk_injury_drafts.py -v

The same rules as the hand-authored drafts, with no exceptions for generated content: tier ai_drafted, the pending-
review source, no citation-like text (the shared guard in app/safety_rules.py, and test_injury_rationale.py's own
check over every stored reason), only known injury areas, and token use recorded apart from live agent_runs.
"""

import csv
import json

import pytest

from app.config import CONTENT_DIR
from app.db import connect
from app.db.draft_injury_tags import BatchDraft, ExerciseDraft, problems
from app.safety_rules import INJURY_FLAGS, RATIONALE_CITATION_LIKE, RATIONALE_PENDING_SOURCE

FEDB = CONTENT_DIR / "exercises" / "source_free_exercise_db"
DRAFTS = json.loads((FEDB / "injury_tags_ai_drafted.json").read_text(encoding="utf-8"))
LIBRARY = {e["id"] for e in json.loads((FEDB / "exercises.json").read_text(encoding="utf-8"))}


def test_every_draft_follows_the_hard_rules():
    assert set(DRAFTS["drafts"]) <= LIBRARY
    for ex_id, d in DRAFTS["drafts"].items():
        tags = d["injury_contraindications"]
        assert set(tags) <= set(INJURY_FLAGS) and len(tags) == len(set(tags)), ex_id
        assert set(d["injury_rationale"]) == set(tags), ex_id
        for injury, r in d["injury_rationale"].items():
            assert r["tier"] == "ai_drafted" and r["source"] == RATIONALE_PENDING_SOURCE, (ex_id, injury)
            assert not RATIONALE_CITATION_LIKE.search(r["reasoning"]), (ex_id, injury)


def test_the_database_carries_exactly_the_drafts(test_db):
    conn = connect()
    try:
        rows = {r["id"]: r for r in conn.execute(
            "SELECT id, contraindication_status, injury_contraindications, injury_rationale FROM exercises "
            "WHERE source_dataset = 'free-exercise-db'")}
    finally:
        conn.close()
    assert set(rows) == LIBRARY
    for ex_id, r in rows.items():
        d = DRAFTS["drafts"].get(ex_id)
        if d is None:                                         # failed or not drafted: still unchecked, as before
            assert r["contraindication_status"] == "untagged" and json.loads(r["injury_contraindications"]) == []
        else:
            assert r["contraindication_status"] == "draft"
            assert json.loads(r["injury_contraindications"]) == d["injury_contraindications"]
            assert json.loads(r["injury_rationale"]) == {k: {kk: v[kk] for kk in ("reasoning", "tier", "source")}
                                                         for k, v in d["injury_rationale"].items()}


def test_cautions_are_not_forced_onto_every_exercise():
    """Not every exercise needs a caution for every area: plenty have one, some have none."""
    counts = [len(d["injury_contraindications"]) for d in DRAFTS["drafts"].values()]
    assert any(c == 0 for c in counts) and sum(c == len(INJURY_FLAGS) for c in counts) < len(counts) / 20


def test_token_use_is_logged_apart_from_live_agent_runs(test_db):
    rows = list(csv.DictReader((FEDB / DRAFTS["generation"]["log"]).open(encoding="utf-8")))
    g = DRAFTS["generation"]
    assert g["calls"] == len(rows) and g["total_tokens"] == sum(int(r["total_tokens"]) for r in rows) > 0
    assert g["input_tokens"] + g["output_tokens"] == g["total_tokens"]
    assert all(r["model"] == "gpt-6-luna" for r in rows)
    conn = connect()
    try:   # the shipped database has no agent_runs rows for this: it was never a live, user-facing call
        assert conn.execute("SELECT COUNT(*) FROM agent_runs WHERE agent_name = 'injury_tag_drafter'").fetchone()[0] == 0
    finally:
        conn.close()


@pytest.mark.parametrize("reason, ok", [
    ("Squatting bends the knee deeply under load, which can aggravate a sore knee.", True),
    ("Research shows squats load the knee joint, which can aggravate a sore knee.", False),
    ("A 2019 review found deep squats load the knee and can aggravate a sore knee.", False),
    ("Too short.", False),
])
def test_the_generator_rejects_citation_like_or_thin_reasons(reason, ok):
    draft = ExerciseDraft(exercise_id="x", cautions=[{"injury": "knee", "reasoning": reason}])
    assert (problems(draft) == []) is ok


def test_the_generator_only_accepts_known_injury_areas():
    with pytest.raises(Exception):
        BatchDraft(results=[{"exercise_id": "x", "cautions": [{"injury": "elbow", "reasoning": "x" * 50}]}])

"""Read-only searches over exercises.

Everything here opens the database read-only (see app.db.connect_readonly). The injury filters are
SQL, not prompt text: a contraindicated exercise is never returned, whatever the caller asks for.

Honesty rule used in every response: an exercise with no injury tags is NOT confirmed safe. Untagged
exercises are returned with injury_check = "not_yet_checked" and a plain-language note, and are never
described as safe.
"""

import json
import re
import sqlite3
from typing import Literal, get_args

from app.content import REVIEW_NOTICE
from app.db import connect_readonly
from app.safety_rules import INJURY_FLAGS

MuscleGroup = Literal["legs", "arms", "chest", "shoulders", "back", "core", "full_body"]
InjuryFlag = Literal["neck", "shoulder", "upper_back", "lower_back", "wrist", "hip", "knee", "ankle"]

MUSCLE_GROUPS = ("legs", "arms", "chest", "shoulders", "back", "core", "full_body")
assert set(get_args(InjuryFlag)) == set(INJURY_FLAGS), "InjuryFlag must match safety_rules.INJURY_FLAGS"
MAX_LIMIT = 50

# Callers (an LLM) may use natural names; map them onto the equipment values stored in the database.
EQUIPMENT_ALIASES = {
    "bodyweight": "none", "body_only": "none", "no_equipment": "none", "none": "none",
    "dumbbell": "dumbbells", "dumbbells": "dumbbells",
    "band": "resistance_band", "bands": "resistance_band", "resistance_band": "resistance_band",
    "resistance_bands": "resistance_band",
    "kettlebell": "kettlebells", "kettlebells": "kettlebells",
    "foam_roll": "foam_roller", "foam_roller": "foam_roller",
    "exercise_ball": "exercise_ball", "stability_ball": "exercise_ball",
    "medicine_ball": "medicine_ball", "ez_curl_bar": "ez_curl_bar", "e_z_curl_bar": "ez_curl_bar",
    "mat": "mat", "yoga_mat": "mat", "chair": "chair", "bench": "bench",
    "barbell": "barbell", "machine": "machine", "cable": "cable", "other": "other",
}


class ToolInputError(ValueError):
    """Bad arguments from the caller. The server turns this into an MCP tool error the model can read."""


def _clean_flags(injury_flags: list[str] | None) -> list[str]:
    flags = sorted(set(injury_flags or []))
    bad = [f for f in flags if f not in INJURY_FLAGS]
    if bad:
        raise ToolInputError(f"Unknown injury flag(s) {bad}. Valid: {list(INJURY_FLAGS)}.")
    return flags


def _clean_equipment(equipment: list[str] | str | None) -> list[str] | None:
    if equipment is None:
        return None
    items = [equipment] if isinstance(equipment, str) else list(equipment)
    cleaned = set()
    for raw in items:
        key = re.sub(r"[\s-]+", "_", str(raw).strip().lower())
        if key not in EQUIPMENT_ALIASES:
            raise ToolInputError(f"Unknown equipment '{raw}'. Valid: {sorted(set(EQUIPMENT_ALIASES.values()))}.")
        cleaned.add(EQUIPMENT_ALIASES[key])
    return sorted(cleaned)


# ---------------------------------------------------------------- injury-safety wording (shared)

INJURY_CHECK = {
    "untagged": ("not_yet_checked",
                 "Not yet checked for injury safety. Do not treat this as safe for any injury."),
    "draft": ("drafted_not_pt_reviewed",
              "Injury cautions are a draft that a physical therapist has not reviewed yet."),
    "pt_reviewed": ("pt_reviewed", "Injury cautions reviewed by a physical therapist."),
}


def _review(row: sqlite3.Row) -> dict:
    return {
        "status": row["status"],
        "review_notice": REVIEW_NOTICE if row["status"] == "placeholder" else None,
        "citations": json.loads(row["citations"]),
    }


# ---------------------------------------------------------------- exercises

# True when NONE of the exercise's contraindications is in the caller's injury flags.
NOT_CONTRAINDICATED = (
    "NOT EXISTS (SELECT 1 FROM json_each(e.injury_contraindications) c "
    "WHERE c.value IN (SELECT value FROM json_each(:flags)))"
)

# True when every piece of equipment the exercise needs is something the caller has (or is "none").
EQUIPMENT_AVAILABLE = (
    "NOT EXISTS (SELECT 1 FROM json_each(e.equipment_needed) n "
    "WHERE n.value <> 'none' AND n.value NOT IN (SELECT value FROM json_each(:equipment)))"
)


def search_exercises(
    muscle_group: str | None = None,
    equipment: list[str] | str | None = None,
    injury_flags: list[str] | None = None,
    limit: int = 20,
    checked_only: bool = False,
) -> dict:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ToolInputError(f"limit must be a whole number from 1 to {MAX_LIMIT}.")
    return _search(muscle_group, equipment, injury_flags, limit, checked_only)


def search_all_exercises(muscle_group: str | None = None, equipment: list[str] | str | None = None,
                         injury_flags: list[str] | None = None, checked_only: bool = False) -> dict:
    """The same search with no row limit, for the plan generator (which ranks the whole filtered pool itself). The
    filters are exactly search_exercises' SQL; only the LIMIT differs. Not exposed as an MCP tool."""
    return _search(muscle_group, equipment, injury_flags, None, checked_only)


def _search(muscle_group, equipment, injury_flags, limit: int | None, checked_only: bool) -> dict:
    if muscle_group is not None and muscle_group not in MUSCLE_GROUPS:
        raise ToolInputError(f"Unknown muscle_group '{muscle_group}'. Valid: {list(MUSCLE_GROUPS)}.")
    flags = _clean_flags(injury_flags)
    have = _clean_equipment(equipment)

    where, params = ["1 = 1"], {"flags": json.dumps(flags), "equipment": json.dumps(have or [])}
    if muscle_group:
        where.append("e.muscle_group = :muscle_group")
        params["muscle_group"] = muscle_group
    if have is not None:
        where.append(EQUIPMENT_AVAILABLE)
    if checked_only:
        where.append("e.contraindication_status <> 'untagged'")
    base = " AND ".join(where)
    inj = f" AND {NOT_CONTRAINDICATED}" if flags else ""

    conn = connect_readonly()
    try:
        total_before_injury_filter = conn.execute(f"SELECT COUNT(*) FROM exercises e WHERE {base}", params).fetchone()[0]
        total = conn.execute(f"SELECT COUNT(*) FROM exercises e WHERE {base}{inj}", params).fetchone()[0]
        # Checked-for-safety exercises first, so a small limit isn't filled entirely by unchecked ones.
        rows = conn.execute(
            f"SELECT e.* FROM exercises e WHERE {base}{inj} "
            "ORDER BY (e.contraindication_status = 'untagged'), e.source_dataset = 'free-exercise-db', e.name "
            "LIMIT :limit", {**params, "limit": -1 if limit is None else limit}).fetchall()
        unchecked_in_pool = conn.execute(
            f"SELECT COUNT(*) FROM exercises e WHERE {base}{inj} AND e.contraindication_status = 'untagged'",
            params).fetchone()[0]
    finally:
        conn.close()

    exercises = []
    for r in rows:
        check, note = INJURY_CHECK[r["contraindication_status"]]
        exercises.append({
            "id": r["id"],
            "name": r["name"],
            "muscle_group": r["muscle_group"],
            "equipment_needed": json.loads(r["equipment_needed"]),
            "difficulty": r["difficulty"],
            "est_time_seconds": r["est_time_seconds"],
            "category": r["category"],
            "force": r["force"],
            "primary_muscles": json.loads(r["primary_muscles"]),
            "injury_contraindications": json.loads(r["injury_contraindications"]),
            "injury_check": check,
            "injury_unchecked": r["contraindication_status"] == "untagged",
            "injury_note": note,
            "source_dataset": r["source_dataset"],
            **_review(r),
        })

    result = {
        "count": len(exercises),
        "total_matching": total,
        "exercises": exercises,
        "injury_filter": {
            "applied": bool(flags),
            "flags": flags,
            "excluded_as_contraindicated": total_before_injury_filter - total if flags else 0,
            "checked_only": checked_only,
            "unchecked_in_matching": unchecked_in_pool,
            "note": ("Exercises tagged as unsafe for these injuries were removed by the database query. "
                     if flags else "No injury filter was applied. ")
                    + "Exercises with injury_check 'not_yet_checked' have NO injury tags because nobody has "
                      "reviewed them yet; that does not mean they are safe. Pass checked_only=true to return only "
                      "exercises that have injury tags (draft or PT-reviewed)."
        },
    }
    if total > len(exercises):
        result["truncated"] = f"Showing {len(exercises)} of {total}. Narrow the search or raise limit (max {MAX_LIMIT})."
    return result


def contraindicated_exercises(injury_flags: list[str], muscle_groups: list[str],
                              equipment: list[str] | None = None, checked_only: bool = True) -> list[dict]:
    """The exercises the injury filter removes for these flags (same equipment / checked_only scope as
    search_exercises), each with the drafted reasoning for every matching tag. For the plan's "left out
    for your injury" list; code only, never sent to the model."""
    flags = _clean_flags(injury_flags)
    have = _clean_equipment(equipment)
    if not flags or not muscle_groups:
        return []
    params = {"flags": json.dumps(flags), "equipment": json.dumps(have or []), "groups": json.dumps(muscle_groups)}
    where = ["e.muscle_group IN (SELECT value FROM json_each(:groups))", f"NOT ({NOT_CONTRAINDICATED})"]
    if have is not None:
        where.append(EQUIPMENT_AVAILABLE)
    if checked_only:
        where.append("e.contraindication_status <> 'untagged'")
    conn = connect_readonly()
    try:
        rows = conn.execute(f"SELECT * FROM exercises e WHERE {' AND '.join(where)} ORDER BY e.name", params).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        rationale = json.loads(r["injury_rationale"])
        out.append({
            "exercise_id": r["id"], "name": r["name"], "muscle_group": r["muscle_group"],
            "cautions": [{"injury": i, **rationale.get(i, {"reasoning": None, "tier": None, "source": None})}
                         for i in json.loads(r["injury_contraindications"]) if i in flags],
        })
    return out

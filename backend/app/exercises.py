"""Exercise library and favorites.

Routes:
  GET    /api/exercises?group=&avoid=&equipment=&source=
                                                the library (full detail for each exercise), filtered like the
                                                quiz reads: a workout group to focus on (upper | lower |
                                                mobility_core, the plans' own groups) and body areas to avoid
                                                because of an injury (the quiz's injury flags; can repeat). avoid
                                                runs through the SAME safety search as the plan generator
                                                (app.mcp_server.search.search_all_exercises with checked_only):
                                                exercises tagged risky for any of those areas are left out, and so
                                                is every untagged exercise, because untagged is never assumed safe.
                                                equipment (can repeat) matches exercises that USE any of the chosen
                                                items (none = bodyweight). Different filters are ANDed. The old
                                                muscle_group, difficulty and injury_status filters were removed
                                                2026-10-25.
  GET    /api/exercises/equipment              every equipment value used by any exercise (live, from the data);
                                                what Build Your Own and the library filter offer, so the pickers
                                                can never drift from the exercises themselves
  GET    /api/exercises/{id}                    one exercise in full detail
  GET    /api/favorites                         the signed-in user's faved exercises, in full detail
  POST   /api/favorites {exercise_id}           fave an exercise (idempotent)
  DELETE /api/favorites/{exercise_id}           un-fave it (idempotent)
Favorites need a sign-in token; the user comes from the token, never from the URL or body.
"""

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.content import media_url, review_info
from app.mcp_server.search import InjuryFlag, search_all_exercises
from app.safety_rules import checked_only_for
from app.security import token_user_id
from app.services.workout_review import workout_groups
from app.users import db

router = APIRouter(prefix="/api")

# The library's focus filter: the groups the generated plans are built from (cardio days prescribe no exercise).
# Each exercise's group comes from app.services.workout_review.workout_groups, the Workout Reviewer's sorting.
WorkoutGroup = Literal["upper", "lower", "mobility_core"]
# Friendlier names for a few equipment values; any other value is shown as itself ("dumbbells" -> "Dumbbells").
EQUIPMENT_LABELS = {
    "none": "Bodyweight", "resistance_band": "Resistance band", "ez_curl_bar": "EZ curl bar",
    "exercise_ball": "Exercise ball", "medicine_ball": "Medicine ball", "foam_roller": "Foam roller",
    "kettlebells": "Kettlebell", "chair": "Sturdy chair", "other": "Other equipment",
}

# One query shape for every exercise response; the source registry entry comes along for the credit line.
SELECT_EXERCISE = """
    SELECT e.*, s.name AS source_name, s.url AS source_url, s.license AS source_license,
           s.status AS source_status
    FROM exercises e JOIN sources s ON s.id = e.source_dataset
"""


def exercise_dict(r: sqlite3.Row) -> dict:
    url = media_url(r["demo_media_path"])
    return {
        "id": r["id"],
        "name": r["name"],
        "muscle_group": r["muscle_group"],
        "equipment_needed": json.loads(r["equipment_needed"]),
        "difficulty": r["difficulty"],
        "force": r["force"],   # push | pull | static | None (no single direction)
        "category": r["category"],
        # which of the plans' groups it counts toward: cardio | upper | lower | mobility_core
        "workout_groups": list(workout_groups(dict(r))),
        "primary_muscles": json.loads(r["primary_muscles"]),
        "secondary_muscles": json.loads(r["secondary_muscles"]),
        "injury_contraindications": json.loads(r["injury_contraindications"]),
        "contraindication_status": r["contraindication_status"],
        # {injury: {reasoning, tier, source}}, one per tag; tier "ai_drafted" until a PT reviews it
        "injury_rationale": json.loads(r["injury_rationale"]),
        "est_time_seconds": r["est_time_seconds"],
        "instructions": r["instructions"],
        # media_type says how to render demo_media_url; both are None until the file exists.
        "demo_media_url": url,
        "media_type": r["media_type"] if url else None,
        "source_dataset": r["source_dataset"],
        "source": {"name": r["source_name"], "url": r["source_url"], "license": r["source_license"],
                   "status": r["source_status"]},
        **review_info(r),
    }


@router.get("/exercises")
def list_exercises(
    group: WorkoutGroup | None = Query(None, description="upper | lower | mobility_core"),
    avoid: list[InjuryFlag] = Query([], description="body areas to avoid because of an injury (quiz flags)"),
    source: str | None = Query(None, description="source_dataset id, e.g. free-exercise-db"),
    equipment: list[str] = Query([], description="exercises that use any of these (none = bodyweight); "
                                                 "valid values: GET /api/exercises/equipment"),
    conn: sqlite3.Connection = Depends(db),
) -> list[dict]:
    sql, args = SELECT_EXERCISE + " WHERE 1 = 1", []
    if source:
        sql += " AND e.source_dataset = ?"
        args.append(source)
    if equipment:
        known = set(equipment_values(conn))
        unknown = sorted(set(equipment) - known)
        if unknown:
            raise HTTPException(422, f"Unknown equipment {unknown}. Valid: {sorted(known)}.")
        sql += (" AND EXISTS (SELECT 1 FROM json_each(e.equipment_needed) n"
                " WHERE n.value IN (SELECT value FROM json_each(?)))")
        args.append(json.dumps(sorted(set(equipment))))
    sql += " ORDER BY e.source_dataset = 'free-exercise-db', e.name"
    items = [exercise_dict(r) for r in conn.execute(sql, args).fetchall()]
    if avoid:
        # Not a second, library-only check: the exact search the plan generator and the MCP tool use, with
        # checked_only forced on for any flag (safety_rules.checked_only_for), so untagged exercises drop out too.
        flags = sorted(set(avoid))
        safe = {e["id"] for e in search_all_exercises(injury_flags=flags,
                                                      checked_only=checked_only_for(flags))["exercises"]}
        items = [e for e in items if e["id"] in safe]
    if group:
        items = [e for e in items if group in e["workout_groups"]]
    return items


def equipment_values(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT n.value FROM exercises e, json_each(e.equipment_needed) n ORDER BY n.value")]


@router.get("/exercises/equipment")
def equipment_options(conn: sqlite3.Connection = Depends(db)) -> list[dict]:
    """Every equipment value that appears on any exercise, with how many exercises use it. Bodyweight ("none")
    comes first and is flagged always_included: bodyweight moves never need equipment, so they're always in."""
    rows = conn.execute(
        "SELECT n.value AS value, COUNT(DISTINCT e.id) AS exercises FROM exercises e, json_each(e.equipment_needed) n "
        "GROUP BY n.value ORDER BY n.value = 'none' DESC, COUNT(DISTINCT e.id) DESC, n.value").fetchall()
    return [{"value": r["value"], "label": EQUIPMENT_LABELS.get(r["value"], r["value"].replace("_", " ").capitalize()),
             "exercises": r["exercises"], "always_included": r["value"] == "none"} for r in rows]


@router.get("/exercises/{exercise_id}")
def get_exercise(exercise_id: str, conn: sqlite3.Connection = Depends(db)) -> dict:
    row = conn.execute(SELECT_EXERCISE + " WHERE e.id = ?", (exercise_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Exercise not found.")
    return exercise_dict(row)


# ---------------------------------------------------------------- favorites

class FavoriteIn(BaseModel):
    exercise_id: str


@router.get("/favorites")
def list_favorites(uid: int = Depends(token_user_id), conn: sqlite3.Connection = Depends(db)) -> list[dict]:
    rows = conn.execute(
        SELECT_EXERCISE + " JOIN exercise_favorites f ON f.exercise_id = e.id WHERE f.user_id = ?"
        " ORDER BY f.created_at DESC, f.id DESC", (uid,)).fetchall()
    return [exercise_dict(r) for r in rows]


@router.post("/favorites")
def add_favorite(body: FavoriteIn, uid: int = Depends(token_user_id),
                 conn: sqlite3.Connection = Depends(db)) -> dict:
    if not conn.execute("SELECT 1 FROM exercises WHERE id = ?", (body.exercise_id,)).fetchone():
        raise HTTPException(404, "Exercise not found.")
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
        raise HTTPException(401, "Your sign-in is invalid or expired. Please sign in again.")  # deleted account
    # The UNIQUE (user_id, exercise_id) constraint makes repeats harmless.
    conn.execute("INSERT OR IGNORE INTO exercise_favorites (user_id, exercise_id) VALUES (?, ?)",
                 (uid, body.exercise_id))
    conn.commit()
    return {"exercise_id": body.exercise_id, "favorited": True}


@router.delete("/favorites/{exercise_id}")
def remove_favorite(exercise_id: str, uid: int = Depends(token_user_id),
                    conn: sqlite3.Connection = Depends(db)) -> dict:
    conn.execute("DELETE FROM exercise_favorites WHERE user_id = ? AND exercise_id = ?", (uid, exercise_id))
    conn.commit()
    return {"exercise_id": exercise_id, "favorited": False}

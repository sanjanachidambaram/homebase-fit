"""Exercise library and favorites.

Routes:
  GET    /api/exercises?muscle_group=&source=&equipment=&difficulty=&injury_status=
                                                the library (full detail for each exercise). equipment,
                                                difficulty and injury_status can repeat (?difficulty=beginner
                                                &difficulty=intermediate); values within one filter are ORed,
                                                different filters are ANDed. equipment matches exercises that
                                                USE any of the chosen items (none = bodyweight).
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
from app.security import token_user_id
from app.users import db

router = APIRouter(prefix="/api")

MuscleGroup = Literal["legs", "arms", "chest", "shoulders", "back", "core", "full_body"]
# Friendlier names for a few equipment values; any other value is shown as itself ("dumbbells" -> "Dumbbells").
EQUIPMENT_LABELS = {
    "none": "Bodyweight", "resistance_band": "Resistance band", "ez_curl_bar": "EZ curl bar",
    "exercise_ball": "Exercise ball", "medicine_ball": "Medicine ball", "foam_roller": "Foam roller",
    "kettlebells": "Kettlebell", "chair": "Sturdy chair", "other": "Other equipment",
}
Difficulty = Literal["beginner", "intermediate", "advanced"]
# untagged = nobody has checked it; draft = cautions drafted, not PT-reviewed; pt_reviewed = confirmed by a PT
InjuryStatus = Literal["untagged", "draft", "pt_reviewed"]

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
    muscle_group: MuscleGroup | None = None,
    source: str | None = Query(None, description="source_dataset id, e.g. free-exercise-db"),
    equipment: list[str] = Query([], description="exercises that use any of these (none = bodyweight); "
                                                 "valid values: GET /api/exercises/equipment"),
    difficulty: list[Difficulty] = Query([]),
    injury_status: list[InjuryStatus] = Query([], description="untagged | draft | pt_reviewed"),
    conn: sqlite3.Connection = Depends(db),
) -> list[dict]:
    sql, args = SELECT_EXERCISE + " WHERE 1 = 1", []
    if muscle_group:
        sql += " AND e.muscle_group = ?"
        args.append(muscle_group)
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
    if difficulty:
        sql += " AND e.difficulty IN (SELECT value FROM json_each(?))"
        args.append(json.dumps(sorted(set(difficulty))))
    if injury_status:
        sql += " AND e.contraindication_status IN (SELECT value FROM json_each(?))"
        args.append(json.dumps(sorted(set(injury_status))))
    sql += " ORDER BY e.source_dataset = 'free-exercise-db', e.name"
    return [exercise_dict(r) for r in conn.execute(sql, args).fetchall()]


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

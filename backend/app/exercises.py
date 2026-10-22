"""Exercise library and favorites.

Routes:
  GET    /api/exercises?muscle_group=&source=   the library (full detail for each exercise)
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
        "category": r["category"],
        "primary_muscles": json.loads(r["primary_muscles"]),
        "secondary_muscles": json.loads(r["secondary_muscles"]),
        "injury_contraindications": json.loads(r["injury_contraindications"]),
        "contraindication_status": r["contraindication_status"],
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
    conn: sqlite3.Connection = Depends(db),
) -> list[dict]:
    sql, args = SELECT_EXERCISE + " WHERE 1 = 1", []
    if muscle_group:
        sql += " AND e.muscle_group = ?"
        args.append(muscle_group)
    if source:
        sql += " AND e.source_dataset = ?"
        args.append(source)
    sql += " ORDER BY e.source_dataset = 'free-exercise-db', e.name"
    return [exercise_dict(r) for r in conn.execute(sql, args).fetchall()]


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

"""Cardio log: what the user did on a non-strength day. A log, not a recommendation; no AI anywhere.

Routes (sign-in required; the user always comes from the token):
  GET    /api/cardio/exercises      the library's cardio exercises (free-exercise-db category "cardio")
  GET    /api/cardio?start=&end=    the user's cardio logs (also included in GET /api/calendar)
  POST   /api/cardio                {date, activity?, exercise_id?, duration_minutes}
  DELETE /api/cardio/{id}

Rules (shared_rules.md rule 9):
  * Free text ("ran 20 min") or one of the library's cardio exercises, plus minutes. Not for future dates.
  * `activity` is the user's own words, like calendar notes: never sent to any model, and checked in code for red
    flags when saved. A match still saves the log, returns a supportive message, and writes a safety_events row
    (source 'cardio_log').
  * Each log writes one workout_logs row (duration, and the exercise if one was picked; not the text), so the Coach's
    streak and rest-day checks see the activity. Deleting the log deletes that row.
  * Pregnant / postpartum users CAN log, in their own words only: no library exercises (a list of exercises would
    read as a suggestion, and they have no plan). Their red-flag message points to their OB-GYN or midwife.
"""

import json
import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.agents.safety import log_safety_event, red_flags_in
from app import calendar as cal   # cal.today(), so a frozen 'today' in tests applies here too
from app.calendar import COMPLETE_GRACE_DAYS, signed_in
from app.db import connect
from app.safety_rules import CLINICAL_REVIEW_PAGE, profile_needs_clinical_review

router = APIRouter(prefix="/api")

MAX_RANGE_DAYS = 62
CARDIO_SUPPORT_MESSAGE = (
    "Your log is saved. It sounds like something hurt or didn't feel right, and that's worth taking seriously. "
    "Please stop any activity that causes it and check in with a doctor or physical therapist. If it's severe or "
    "sudden, like chest pain, trouble breathing, or fainting, get medical help right away.")
CARDIO_SUPPORT_PREGNANCY = (
    "Your log is saved. Some of what you wrote can be a warning sign during pregnancy or after giving birth. Please "
    "stop the activity and contact your OB-GYN or midwife. If it's severe or sudden, like heavy bleeding, chest pain, "
    "trouble breathing, or fainting, get medical help right away.")


def _dict(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "date": r["date"], "activity": r["activity"], "exercise_id": r["exercise_id"],
            "exercise_name": r["exercise_name"], "duration_minutes": r["duration_minutes"], "created_at": r["created_at"]}


def cardio_logs_between(uid: int, start: date, end: date) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT c.*, e.name AS exercise_name FROM cardio_logs c LEFT JOIN exercises e ON e.id = c.exercise_id "
            "WHERE c.user_id = ? AND c.date BETWEEN ? AND ? ORDER BY c.date, c.id",
            (uid, start.isoformat(), end.isoformat())).fetchall()
    finally:
        conn.close()
    return [_dict(r) for r in rows]


@router.get("/cardio/exercises")
def cardio_exercises() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute("SELECT id, name, equipment_needed, difficulty FROM exercises WHERE category = 'cardio' "
                            "ORDER BY name").fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "name": r["name"], "equipment_needed": json.loads(r["equipment_needed"]),
             "difficulty": r["difficulty"]} for r in rows]


@router.get("/cardio")
def list_cardio(start: date = Query(...), end: date = Query(...), uid: int = Depends(signed_in)) -> list[dict]:
    if end < start or (end - start).days >= MAX_RANGE_DAYS:
        raise HTTPException(422, f"end must be on or after start, at most {MAX_RANGE_DAYS} days in all.")
    return cardio_logs_between(uid, start, end)


class CardioIn(BaseModel):
    model_config = {"extra": "forbid"}
    date: date
    activity: str | None = Field(None, max_length=80)
    exercise_id: str | None = Field(None, max_length=100)
    duration_minutes: int = Field(ge=1, le=600)

    @model_validator(mode="after")
    def _something(self):
        self.activity = (self.activity or "").strip() or None
        if not self.activity and not self.exercise_id:
            raise ValueError("Say what you did (like 'brisk walk') or pick a cardio exercise.")
        return self


@router.post("/cardio", status_code=201)
def log_cardio(body: CardioIn, uid: int = Depends(signed_in)) -> dict:
    if body.date > cal.today() + timedelta(days=COMPLETE_GRACE_DAYS):
        raise HTTPException(422, "Log activity on or after the day you did it, not before.")
    clinical = profile_needs_clinical_review(uid)
    if clinical and body.exercise_id:
        raise HTTPException(403, {"code": "needs_clinical_review", "page": CLINICAL_REVIEW_PAGE,
                                  "message": "While you're pregnant or postpartum, log activity in your own words; "
                                             "picking from the exercise library is paused."})
    conn = connect()
    try:
        if body.exercise_id and not conn.execute(
                "SELECT 1 FROM exercises WHERE id = ? AND category = 'cardio'", (body.exercise_id,)).fetchone():
            raise HTTPException(422, "That isn't one of the library's cardio exercises.")
        with conn:
            log_id = conn.execute(
                "INSERT INTO cardio_logs (user_id, date, activity, exercise_id, duration_minutes) VALUES (?, ?, ?, ?, ?)",
                (uid, body.date.isoformat(), body.activity, body.exercise_id, body.duration_minutes)).lastrowid
            conn.execute(   # activity for the Coach's streak / rest checks; the user's text is NOT copied
                "INSERT INTO workout_logs (user_id, date, exercise_id, duration_seconds, cardio_log_id) VALUES (?, ?, ?, ?, ?)",
                (uid, body.date.isoformat(), body.exercise_id, body.duration_minutes * 60, log_id))
        row = conn.execute("SELECT c.*, e.name AS exercise_name FROM cardio_logs c LEFT JOIN exercises e "
                           "ON e.id = c.exercise_id WHERE c.id = ?", (log_id,)).fetchone()
    finally:
        conn.close()

    # Same code-only red-flag check as calendar notes and the Basics Q&A. The log stays saved either way.
    safety = {"flagged": False}
    flags = red_flags_in(body.activity or "")
    if flags:
        event_id = log_safety_event(uid, "cardio_log", body.activity, "log_saved_pointed_to_professional")
        safety = {"flagged": True, "red_flags": flags, "safety_event_id": event_id,
                  "message": CARDIO_SUPPORT_PREGNANCY if clinical else CARDIO_SUPPORT_MESSAGE}
    return {"log": _dict(row), "safety": safety, "agent_called": False}


@router.delete("/cardio/{log_id}")
def delete_cardio(log_id: int, uid: int = Depends(signed_in)) -> dict:
    conn = connect()
    try:
        with conn:
            n = conn.execute("DELETE FROM cardio_logs WHERE id = ? AND user_id = ?", (log_id, uid)).rowcount
    finally:
        conn.close()
    if not n:
        raise HTTPException(404, "Log not found.")
    return {"deleted": True}

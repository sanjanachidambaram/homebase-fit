"""Cardio log: what the user did on a non-strength day. A log, not a recommendation; no AI anywhere.

Routes (sign-in required; the user always comes from the token):
  GET    /api/cardio/types          activity types (walking, running, ...) and which measures each one takes
  GET    /api/cardio/exercises      the library's cardio exercises (free-exercise-db category "cardio"), with their type
  GET    /api/cardio?start=&end=    the user's cardio logs (also included in GET /api/calendar)
  POST   /api/cardio                {date, activity?, exercise_id?, cardio_type?, measure, duration_minutes? |
                                     steps? | distance + distance_unit?}
  DELETE /api/cardio/{id}

Rules (shared_rules.md rule 9):
  * Free text ("ran 20 min") or one of the library's cardio exercises, measured in minutes, steps, or distance.
    Not for future dates.
  * Each log gets a calorie range computed in code (app/services/cardio_estimate.py: the Workout Reviewer's
    Compendium MET method and the profile's weight). No AI. None for "other" activities, and none at all for
    pregnant / postpartum users.
  * Logging onto a calendar day that's a rest, open or cardio day turns it into a done cardio day (a custom day, so
    "Use my plan" brings the planned day back, and a retake keeps it). A strength day stays as it is: its own toggle
    marks it done. Deleting the last cardio log on a cardio day un-marks it.
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
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.agents.safety import log_safety_event, red_flags_in
from app import calendar as cal   # cal.today(), so a frozen 'today' in tests applies here too
from app.calendar import COMPLETE_GRACE_DAYS, signed_in
from app.db import connect
from app.safety_rules import CLINICAL_REVIEW_PAGE, profile_needs_clinical_review
from app.services.cardio_estimate import (CARDIO_TYPES, DISTANCE_TYPES, KM_PER_MILE, LIBRARY_TYPES, STEP_TYPES,
                                          estimate_cardio, types_for_api)

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


def estimate_context(conn: sqlite3.Connection, uid: int) -> dict:
    """What the calorie math needs: the profile's weight, and whether estimates are off (pregnant / postpartum)."""
    row = conn.execute("SELECT weight, needs_clinical_review FROM quiz_profiles WHERE user_id = ?", (uid,)).fetchone()
    return {"weight_lb": row["weight"] if row else None, "clinical": bool(row and row["needs_clinical_review"])}


def log_estimate(r, ctx: dict) -> dict:
    if ctx["clinical"]:   # shared_rules rule 9: no calorie numbers during pregnancy / postpartum
        return {"available": False, "reason": "No calorie estimates while you're pregnant or postpartum."}
    return estimate_cardio(r["cardio_type"], minutes=r["duration_minutes"], steps=r["steps"],
                           miles=r["distance_miles"], weight_lb=ctx["weight_lb"])


def _dict(r: sqlite3.Row, ctx: dict) -> dict:
    return {"id": r["id"], "date": r["date"], "activity": r["activity"], "exercise_id": r["exercise_id"],
            "exercise_name": r["exercise_name"], "cardio_type": r["cardio_type"],
            "cardio_type_label": CARDIO_TYPES.get(r["cardio_type"] or "", {}).get("label"), "measure": r["measure"],
            "duration_minutes": r["duration_minutes"], "steps": r["steps"], "distance_miles": r["distance_miles"],
            "estimate": log_estimate(r, ctx), "created_at": r["created_at"]}


SELECT_LOG = "SELECT c.*, e.name AS exercise_name FROM cardio_logs c LEFT JOIN exercises e ON e.id = c.exercise_id "


def cardio_logs_between(uid: int, start: date, end: date) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(SELECT_LOG + "WHERE c.user_id = ? AND c.date BETWEEN ? AND ? ORDER BY c.date, c.id",
                            (uid, start.isoformat(), end.isoformat())).fetchall()
        ctx = estimate_context(conn, uid)
    finally:
        conn.close()
    return [_dict(r, ctx) for r in rows]


@router.get("/cardio/types")
def cardio_types() -> list[dict]:
    return types_for_api()


@router.get("/cardio/exercises")
def cardio_exercises() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute("SELECT id, name, equipment_needed, difficulty FROM exercises WHERE category = 'cardio' "
                            "ORDER BY name").fetchall()
    finally:
        conn.close()
    return [{"id": r["id"], "name": r["name"], "equipment_needed": json.loads(r["equipment_needed"]),
             "difficulty": r["difficulty"], "cardio_type": LIBRARY_TYPES.get(r["id"], "other")} for r in rows]


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
    cardio_type: str | None = Field(None, max_length=30)
    measure: Literal["duration", "steps", "distance"] = "duration"
    duration_minutes: int | None = Field(None, ge=1, le=600)
    steps: int | None = Field(None, ge=1, le=100000)
    distance: float | None = Field(None, gt=0, le=300)
    distance_unit: Literal["mi", "km"] = "mi"

    @model_validator(mode="after")
    def _something(self):
        self.activity = (self.activity or "").strip() or None
        if not self.activity and not self.exercise_id:
            raise ValueError("Say what you did (like 'brisk walk') or pick a cardio exercise.")
        if self.cardio_type is not None and self.cardio_type not in CARDIO_TYPES:
            raise ValueError(f"cardio_type must be one of {sorted(CARDIO_TYPES)}.")
        given = {"duration": self.duration_minutes, "steps": self.steps, "distance": self.distance}
        if given[self.measure] is None:
            raise ValueError({"duration": "Add how many minutes.", "steps": "Add your step count.",
                              "distance": "Add the distance."}[self.measure])
        if any(v is not None for k, v in given.items() if k != self.measure):
            raise ValueError("Send one measurement: minutes, steps, or distance.")
        return self


def _sync_day(conn: sqlite3.Connection, uid: int, day: str) -> int | None:
    """Keep the calendar day on this date in step with its cardio logs. A rest / open / cardio day with a log becomes
    a done cardio day (custom, so it can go back to the plan); a cardio day with no logs left is un-marked. Strength
    days are left alone. Returns the entry id if it changed."""
    entry = conn.execute("SELECT * FROM calendar_entries WHERE user_id = ? AND date = ?", (uid, day)).fetchone()
    if entry is None or entry["day_type"] == "workout":
        return None
    logs = conn.execute("SELECT COUNT(*) FROM cardio_logs WHERE user_id = ? AND date = ?", (uid, day)).fetchone()[0]
    stamp = cal.now_utc()
    if logs and entry["day_type"] == "rest":
        planned = entry["planned_content"] or json.dumps({"day_type": "rest",
                                                          "workout_content": json.loads(entry["workout_content"])})
        content = cal.cardio_content(None, date.fromisoformat(day))
        conn.execute("UPDATE calendar_entries SET day_type = 'cardio', workout_content = ?, source = 'custom', "
                     "planned_content = ?, completed = 1, updated_at = ? WHERE id = ?",
                     (json.dumps(content), planned, stamp, entry["id"]))
        return entry["id"]
    if entry["day_type"] == "cardio" and bool(entry["completed"]) != bool(logs):
        conn.execute("UPDATE calendar_entries SET completed = ?, updated_at = ? WHERE id = ?",
                     (int(bool(logs)), stamp, entry["id"]))
        return entry["id"]
    return None


@router.post("/cardio", status_code=201)
def log_cardio(body: CardioIn, uid: int = Depends(signed_in)) -> dict:
    if body.date > cal.today() + timedelta(days=COMPLETE_GRACE_DAYS):
        raise HTTPException(422, "Log activity on or after the day you did it, not before.")
    clinical = profile_needs_clinical_review(uid)
    if clinical and body.exercise_id:
        raise HTTPException(403, {"code": "needs_clinical_review", "page": CLINICAL_REVIEW_PAGE,
                                  "message": "While you're pregnant or postpartum, log activity in your own words; "
                                             "picking from the exercise library is paused."})
    # A library pick decides the type; otherwise it's what the user chose (or nothing: no estimate).
    cardio_type = LIBRARY_TYPES.get(body.exercise_id, "other") if body.exercise_id else body.cardio_type
    if body.measure == "steps" and cardio_type not in STEP_TYPES:
        raise HTTPException(422, "Step counts work for walking or hiking. Use minutes or distance for this one.")
    if body.measure == "distance" and cardio_type not in DISTANCE_TYPES:
        raise HTTPException(422, "Distance works for walking, running or cycling. Use minutes for this one.")
    miles = None
    if body.distance is not None:
        miles = round(body.distance / KM_PER_MILE if body.distance_unit == "km" else body.distance, 2)
        if miles > 200:
            raise HTTPException(422, "That distance is more than 200 miles.")
    conn = connect()
    try:
        if body.exercise_id and not conn.execute(
                "SELECT 1 FROM exercises WHERE id = ? AND category = 'cardio'", (body.exercise_id,)).fetchone():
            raise HTTPException(422, "That isn't one of the library's cardio exercises.")
        with conn:
            log_id = conn.execute(
                "INSERT INTO cardio_logs (user_id, date, activity, exercise_id, cardio_type, measure, duration_minutes,"
                " steps, distance_miles) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, body.date.isoformat(), body.activity, body.exercise_id, cardio_type, body.measure,
                 body.duration_minutes, body.steps, miles)).lastrowid
            conn.execute(   # activity for the Coach's streak / rest checks; the user's text is NOT copied
                "INSERT INTO workout_logs (user_id, date, exercise_id, duration_seconds, cardio_log_id) VALUES (?, ?, ?, ?, ?)",
                (uid, body.date.isoformat(), body.exercise_id,
                 body.duration_minutes * 60 if body.duration_minutes else None, log_id))
            day_changed = None if clinical else _sync_day(conn, uid, body.date.isoformat())
        row = conn.execute(SELECT_LOG + "WHERE c.id = ?", (log_id,)).fetchone()
        ctx = estimate_context(conn, uid)
    finally:
        conn.close()

    # Same code-only red-flag check as calendar notes. The log stays saved either way.
    safety = {"flagged": False}
    flags = red_flags_in(body.activity or "")
    if flags:
        event_id = log_safety_event(uid, "cardio_log", body.activity, "log_saved_pointed_to_professional")
        safety = {"flagged": True, "red_flags": flags, "safety_event_id": event_id,
                  "message": CARDIO_SUPPORT_PREGNANCY if clinical else CARDIO_SUPPORT_MESSAGE}
    return {"log": _dict(row, ctx), "calendar_entry_updated": day_changed, "safety": safety, "agent_called": False}


@router.delete("/cardio/{log_id}")
def delete_cardio(log_id: int, uid: int = Depends(signed_in)) -> dict:
    conn = connect()
    try:
        with conn:
            row = conn.execute("SELECT date FROM cardio_logs WHERE id = ? AND user_id = ?", (log_id, uid)).fetchone()
            if row is None:
                raise HTTPException(404, "Log not found.")
            conn.execute("DELETE FROM cardio_logs WHERE id = ?", (log_id,))
            day_changed = _sync_day(conn, uid, row["date"])
    finally:
        conn.close()
    return {"deleted": True, "calendar_entry_updated": day_changed}

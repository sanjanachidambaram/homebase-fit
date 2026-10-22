"""Accounts, the onboarding quiz submission, and full data deletion.

Routes:
  POST   /api/users                       sign up -> {user_id, token}
  POST   /api/login                       sign in -> {user_id, token}
  GET    /api/quiz/questions              the quiz (public)
  GET    /api/users/{id}                  account + quiz profile (own account only)
  PUT    /api/users/{id}/quiz-profile     save quiz answers; REQUIRES consent_accepted = true
  DELETE /api/users/{id}                  permanently delete the user and ALL their data
"""

import json
import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import connect
from app.security import hash_password, make_token, require_same_user, token_user_id, verify_password

router = APIRouter(prefix="/api")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Quiz question id -> quiz_profiles column. The quiz file can change wording and
# options freely, but these ids must stay (see content/quiz/quiz_questions.yaml).
QUIZ_COLUMNS = {
    "goals": "goals", "timeline": "timeline", "injuries": "injury_flags", "age": "age", "weight": "weight",
    "height": "height", "experience_level": "experience_level", "days_available": "days_available",
    "session_length": "session_length_minutes", "equipment": "equipment",
    "other_activity_days": "other_activity_days", "other_activity_notes": "other_activity_notes",
    "pregnancy_status": "pregnancy_status", "goal_weight": "goal_weight", "goal_date": "goal_date",
}
LIST_COLUMNS = {"goals", "injury_flags", "equipment"}
INT_COLUMNS = {"age", "days_available", "session_length_minutes", "other_activity_days"}
TEXT_MAX = 500
GOAL_DATE_MAX_YEARS = 5

# Every table holding a user's data. DELETE /api/users/{id} clears all of them.
# workout_logs goes before calendar_entries (a log can point at a calendar day).
USER_DATA_TABLES = ("safety_events", "measurements", "workout_logs", "calendar_entries", "exercise_favorites",
                    "quiz_profiles")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------- accounts

class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=200)


class AuthResult(BaseModel):
    user_id: int
    token: str


@router.post("/users", status_code=201)
def sign_up(body: Credentials, conn: sqlite3.Connection = Depends(db)) -> AuthResult:
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    try:
        cur = conn.execute("INSERT INTO users (email, password_hash) VALUES (?, ?)",
                           (email, hash_password(body.password)))
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with that email already exists. Sign in instead.")
    return AuthResult(user_id=cur.lastrowid, token=make_token(cur.lastrowid))


@router.post("/login")
def log_in(body: Credentials, conn: sqlite3.Connection = Depends(db)) -> AuthResult:
    row = conn.execute("SELECT id, password_hash FROM users WHERE email = ?",
                       (body.email.strip().lower(),)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    return AuthResult(user_id=row["id"], token=make_token(row["id"]))


def profile_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    p = dict(row)
    for col in ("goals", "injury_flags", "equipment"):
        p[col] = json.loads(p[col])
    p["consent_accepted"] = bool(p["consent_accepted"])
    p["needs_clinical_review"] = bool(p.get("needs_clinical_review"))
    return p


@router.get("/users/{user_id}")
def get_user(user_id: int, uid: int = Depends(token_user_id), conn: sqlite3.Connection = Depends(db)) -> dict:
    require_same_user(user_id, uid)
    user = conn.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(404, "Account not found.")
    profile = conn.execute("SELECT * FROM quiz_profiles WHERE user_id = ?", (user_id,)).fetchone()
    return {**dict(user), "quiz_profile": profile_dict(profile)}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, uid: int = Depends(token_user_id), conn: sqlite3.Connection = Depends(db)) -> dict:
    """Hard delete: the user row and every row of theirs in every user-data table.
    Explicit deletes (not just the ON DELETE CASCADE in schema.sql) so the code
    states exactly what gets removed, and all of it happens in one transaction."""
    require_same_user(user_id, uid)
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        raise HTTPException(404, "Account not found.")
    deleted: dict[str, int] = {}
    with conn:  # one transaction: all or nothing
        for table in USER_DATA_TABLES:
            deleted[table] = conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,)).rowcount
        # The AI token log holds no content, only counts; keep it for the statistics but cut the link.
        unlinked = conn.execute("UPDATE agent_runs SET user_id = NULL WHERE user_id = ?", (user_id,)).rowcount
        deleted["users"] = conn.execute("DELETE FROM users WHERE id = ?", (user_id,)).rowcount
    return {"deleted": True, "rows_removed": deleted, "agent_runs_unlinked": unlinked}


# ---------------------------------------------------------------- quiz

@router.get("/quiz/questions")
def quiz_questions(conn: sqlite3.Connection = Depends(db)) -> list[dict]:
    rows = conn.execute("SELECT * FROM quiz_questions ORDER BY order_index").fetchall()
    return [
        {"id": r["id"], "prompt": r["prompt"], "type": r["question_type"], "options": json.loads(r["options"]),
         "required": bool(r["required"]), **json.loads(r["settings"])}
        for r in rows
    ]


class QuizSubmission(BaseModel):
    consent_accepted: bool                                     # the medical disclaimer checkbox
    consent_version: str = Field(min_length=1, max_length=40)  # which disclaimer text was shown
    answers: dict[str, Any]                                    # question id -> answer
    injury_notes: str | None = Field(None, max_length=1000)    # optional free text under "injuries"


def validate_answer(q: sqlite3.Row, value: Any) -> Any:
    settings = json.loads(q["settings"])
    allowed = {o["value"] for o in json.loads(q["options"])}
    qtype, qid = q["question_type"], q["id"]
    if qtype == "multi_select":
        if not isinstance(value, list) or not all(v in allowed for v in value):
            raise HTTPException(422, f"'{qid}': choose from {sorted(allowed)}.")
        exclusive = settings.get("exclusive")
        if exclusive in value:
            if len(value) > 1:
                raise HTTPException(422, f"'{qid}': '{exclusive}' can't be combined with other choices.")
            return []
        return sorted(set(value))
    if qtype == "single_select":
        if value not in allowed:
            raise HTTPException(422, f"'{qid}': choose one of {sorted(allowed)}.")
        return value
    if qtype == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(422, f"'{qid}' must be a number.")
        lo, hi = settings.get("min"), settings.get("max")
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            raise HTTPException(422, f"'{qid}' must be between {lo} and {hi}.")
        return value
    if qtype == "date":
        try:
            day = date.fromisoformat(str(value))
        except ValueError:
            raise HTTPException(422, f"'{qid}' must be a date like 2027-03-01.")
        today = datetime.now(timezone.utc).date()
        if not today < day <= today.replace(year=today.year + GOAL_DATE_MAX_YEARS):
            raise HTTPException(422, f"'{qid}' must be a future date within {GOAL_DATE_MAX_YEARS} years.")
        return day.isoformat()
    text = str(value).strip()
    if len(text) > TEXT_MAX:
        raise HTTPException(422, f"'{qid}' must be {TEXT_MAX} characters or fewer.")
    return text


@router.put("/users/{user_id}/quiz-profile")
def save_quiz(user_id: int, body: QuizSubmission, uid: int = Depends(token_user_id),
              conn: sqlite3.Connection = Depends(db)) -> dict:
    require_same_user(user_id, uid)
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        raise HTTPException(404, "Account not found.")
    # Consent gate: nothing is stored unless the disclaimer was accepted.
    # (schema.sql enforces the same rule with a CHECK constraint.)
    if not body.consent_accepted:
        raise HTTPException(422, "Please read and accept the medical disclaimer before submitting the quiz.")

    questions = {q["id"]: q for q in conn.execute("SELECT * FROM quiz_questions").fetchall()}
    unknown = set(body.answers) - set(questions)
    if unknown:
        raise HTTPException(422, f"Unknown question id(s): {sorted(unknown)}.")
    values: dict[str, Any] = {}
    for qid, q in questions.items():
        answer = body.answers.get(qid)
        if answer in (None, "", []):
            if q["required"]:
                raise HTTPException(422, f"Please answer: {q['prompt']}")
            continue
        if qid in QUIZ_COLUMNS:
            values[QUIZ_COLUMNS[qid]] = validate_answer(q, answer)

    for col in LIST_COLUMNS:
        values[col] = json.dumps(values.get(col, []))
    for col in INT_COLUMNS & values.keys():
        values[col] = int(values[col])
    values.setdefault("other_activity_days", 0)

    # Every quiz column is written on every save, so a retake clears answers that were left blank.
    row = {col: values.get(col) for col in QUIZ_COLUMNS.values()}
    row.update(user_id=user_id, injury_notes=(body.injury_notes or "").strip() or None,
               consent_accepted=1, consent_accepted_at=now_utc(), consent_version=body.consent_version)
    row["updated_at"] = row["consent_accepted_at"]
    cols = list(row)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "user_id")
    conn.execute(
        f"INSERT INTO quiz_profiles ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT(user_id) DO UPDATE SET {updates}", row)
    conn.commit()
    # Lay the (re)generated plan out on the calendar. Days the user completed or wrote notes on are kept;
    # pregnant / postpartum users get no plan, so only their untouched future days are cleared.
    from app.calendar import materialize_plan   # local import: calendar imports this module's db helpers
    materialize_plan(user_id)
    row = conn.execute("SELECT * FROM quiz_profiles WHERE user_id = ?", (user_id,)).fetchone()
    return profile_dict(row)

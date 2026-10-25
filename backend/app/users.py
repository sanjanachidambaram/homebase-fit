"""Accounts, the onboarding quiz submission, and full data deletion.

Routes:
  POST   /api/users                       sign up -> {user_id, token}
  POST   /api/login                       sign in -> {user_id, token}
  GET    /api/quiz/questions              the quiz (public)
  GET    /api/users/{id}                  account + quiz profile (own account only)
  PUT    /api/users/{id}/quiz-profile     save quiz answers; REQUIRES consent_accepted = true
  DELETE /api/users/{id}/quiz-profile     "Reset my quiz": clear the answers and untouched planned days
  DELETE /api/users/{id}                  permanently delete the user and ALL their data
"""

import json
import logging
import re
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db import connect
from app.security import hash_password, make_token, require_same_user, token_user_id, verify_password

router = APIRouter(prefix="/api")
log = logging.getLogger(__name__)

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
USERNAME_RULE = "3 to 30 characters: letters, numbers, dots, dashes or underscores"
FIRST_NAME_MAX = 50

# Quiz question id -> quiz_profiles column. The quiz file can change wording and
# options freely, but these ids must stay (see content/quiz/quiz_questions.yaml).
# (Rewritten 2026-10-25: one goal; timeline, days, session length, other activity, age, height and goal date are
# no longer asked, and weight / goal weight only on the "Losing weight" path.)
QUIZ_COLUMNS = {
    "goal": "goal", "experience_level": "experience_level", "equipment": "equipment", "injuries": "injury_flags",
    "pregnancy_status": "pregnancy_status", "weight": "weight", "goal_weight": "goal_weight",
}
LIST_COLUMNS = {"injury_flags", "equipment"}
TEXT_MAX = 500
GOAL_DATE_MAX_YEARS = 5

# Every table holding a user's data. DELETE /api/users/{id} clears all of them.
# workout_logs goes before calendar_entries (a log can point at a calendar day).
USER_DATA_TABLES = ("safety_events", "measurements", "workout_logs", "calendar_entries", "cardio_logs",
                    "built_workouts", "exercise_favorites", "quiz_profiles")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


# ---------------------------------------------------------------- accounts

class SignUp(BaseModel):
    username: str = Field(max_length=30)
    first_name: str = Field(max_length=FIRST_NAME_MAX)   # the Dashboard greeting; never sent to any agent
    password: str = Field(min_length=8, max_length=200)


class SignIn(BaseModel):
    username: str = Field(max_length=254)   # 254: accounts from before usernames sign in with their old email
    password: str = Field(min_length=8, max_length=200)


class AuthResult(BaseModel):
    user_id: int
    token: str


@router.post("/users", status_code=201)
def sign_up(body: SignUp, conn: sqlite3.Connection = Depends(db)) -> AuthResult:
    username = body.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(422, f"Pick a username of {USERNAME_RULE}.")
    first_name = " ".join(body.first_name.split())   # trims and collapses whitespace, drops tabs/newlines
    if not first_name:
        raise HTTPException(422, "Enter your first name.")
    try:
        cur = conn.execute("INSERT INTO users (username, first_name, password_hash) VALUES (?, ?, ?)",
                           (username, first_name, hash_password(body.password)))
        conn.commit()
    except sqlite3.IntegrityError:   # usernames are unique ignoring case (schema.sql: COLLATE NOCASE)
        raise HTTPException(409, "That username is taken. Pick another, or sign in if it's yours.")
    return AuthResult(user_id=cur.lastrowid, token=make_token(cur.lastrowid))


@router.post("/login")
def log_in(body: SignIn, conn: sqlite3.Connection = Depends(db)) -> AuthResult:
    row = conn.execute("SELECT id, password_hash FROM users WHERE username = ?",   # NOCASE: any capitalization
                       (body.username.strip(),)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Username or password is incorrect.")
    return AuthResult(user_id=row["id"], token=make_token(row["id"]))


def profile_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    p = dict(row)
    for col in ("injury_flags", "equipment"):
        p[col] = json.loads(p[col])
    p["consent_accepted"] = bool(p["consent_accepted"])
    if "plan_swaps" in p:
        p["plan_swaps"] = json.loads(p["plan_swaps"] or "{}")
        p["plan_reviewed"] = bool(p["plan_reviewed"])
    p["needs_clinical_review"] = bool(p.get("needs_clinical_review"))
    return p


@router.get("/users/{user_id}")
def get_user(user_id: int, uid: int = Depends(token_user_id), conn: sqlite3.Connection = Depends(db)) -> dict:
    require_same_user(user_id, uid)
    user = conn.execute("SELECT id, username, first_name, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
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
        always = settings.get("always_included")          # e.g. bodyweight: always on, even if unticked
        return sorted(set(value) | ({always} if always else set()))
    if qtype == "single_select":
        if not isinstance(value, str) or value not in allowed:   # one choice: a list (or anything else) is refused
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
    for qid, q in sorted(questions.items(), key=lambda kv: kv[1]["order_index"]):
        ask_if = json.loads(q["settings"]).get("ask_if")
        if ask_if and body.answers.get(ask_if["question"]) != ask_if["equals"]:
            continue   # not asked for this answer (e.g. weight unless the goal is losing weight): never stored
        answer = body.answers.get(qid)
        if answer in (None, "", []):
            if q["required"]:
                raise HTTPException(422, f"Please answer: {q['prompt']}")
            continue
        if qid in QUIZ_COLUMNS:
            values[QUIZ_COLUMNS[qid]] = validate_answer(q, answer)

    for col in LIST_COLUMNS:
        values[col] = json.dumps(values.get(col, []))

    # Every quiz column is written on every save, so a retake clears answers that were left blank.
    row = {col: values.get(col) for col in QUIZ_COLUMNS.values()}
    row.update(user_id=user_id, consent_accepted=1, consent_accepted_at=now_utc(), consent_version=body.consent_version)
    row["updated_at"] = row["consent_accepted_at"]
    # A (re)taken quiz is a new plan: progression starts again at week 1 today, and review-mode swaps from the old
    # plan no longer apply (the user reviews the new plan). The calendar mode itself is kept.
    from app.calendar import today as calendar_today   # local import: calendar imports this module's db helpers
    row.update(plan_started_on=calendar_today().isoformat(), plan_swaps="{}", plan_reviewed=0)
    cols = list(row)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "user_id")
    conn.execute(
        f"INSERT INTO quiz_profiles ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
        f"ON CONFLICT(user_id) DO UPDATE SET {updates}", row)
    conn.commit()
    # Lay the (re)generated plan out on the calendar. Days the user completed or wrote notes on are kept;
    # pregnant / postpartum users get no plan, so only their untouched future days are cleared.
    # The answers are already saved. If laying out the calendar fails, log it and still return 200: GET
    # /api/calendar fills it in on the next visit, and the quiz never looks like it failed.
    from app.calendar import materialize_plan   # local import: calendar imports this module's db helpers
    try:
        materialize_plan(user_id)
    except Exception:
        log.exception("Calendar materialization failed after saving the quiz for user %s", user_id)
    row = conn.execute("SELECT * FROM quiz_profiles WHERE user_id = ?", (user_id,)).fetchone()
    return profile_dict(row)


@router.delete("/users/{user_id}/quiz-profile")
def reset_quiz(user_id: int, uid: int = Depends(token_user_id), conn: sqlite3.Connection = Depends(db)) -> dict:
    """Reset my quiz: back to the no-plan state without retaking it now. Deletes the quiz answers (and the consent
    record that came with them; retaking asks for the disclaimer again) and the planned calendar days that nobody
    touched, from today on: the same days a retake would replace. Kept: the account, completed days, days with
    notes, days you built yourself, past days, workout logs, cardio logs, measurements, and favorites."""
    require_same_user(user_id, uid)
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        raise HTTPException(404, "Account not found.")
    from app.calendar import today as calendar_today   # local import: calendar imports this module's db helpers
    with conn:
        profile = conn.execute("DELETE FROM quiz_profiles WHERE user_id = ?", (user_id,)).rowcount
        days = conn.execute(
            "DELETE FROM calendar_entries WHERE user_id = ? AND date >= ? AND completed = 0 "
            "AND (notes IS NULL OR TRIM(notes) = '') AND source = 'generated'",
            (user_id, calendar_today().isoformat())).rowcount
    return {"reset": bool(profile), "calendar_days_cleared": days}

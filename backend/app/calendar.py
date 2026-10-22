"""Calendar: the generated weekly plan laid out on real dates, movable and loggable.

Routes (sign-in required; the user always comes from the token):
  GET   /api/calendar?start=&end=   entries from start to end, inclusive (default: this Monday to Sunday)
  PATCH /api/calendar/{id}          {date?, notes?, completed?}

Rules, all enforced here in code:
  * materialize_plan() runs when the quiz is saved: 4 weeks of entries from today, one per date, following the
    plan's weekly pattern. Each entry's workout_content is a snapshot of that day of the plan.
    A retake REFRESHES only entries dated today or later that are not completed and have no notes. Past days,
    completed days, and days with notes are never touched.
  * Moving a day onto a date that already has one swaps the two. A completed day can't be moved (its
    workout_logs rows are dated), and nothing can be swapped onto a completed day.
  * Marking a workout day completed writes one workout_logs row per exercise (calendar_entry_id set), so the
    Coach's streak / overtraining / goal checks read real logged days. Un-marking removes those rows. Rest days
    can't be marked completed (that would count as a workout), and neither can days that haven't come yet.
  * Notes are the user's own words. They're always saved, and checked in code (app/agents/safety.py, the same
    red-flag check as the Basics Q&A) when they change. A match logs a safety_events row (source
    'calendar_note') and returns a supportive message pointing to a doctor or PT. No AI call, ever: notes are
    never sent to any model (shared_rules.md rule 2) and no MCP tool reads them.
  * Pregnant / postpartum users have no plan: GET returns an empty calendar that points to /pregnancy-support.
"""

import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from datetime import date as Day   # for the CalendarUpdate.date field, whose name shadows the type

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.agents.safety import NOTE_SUPPORT_MESSAGE, log_safety_event, red_flags_in
from app.db import connect
from app.safety_rules import CLINICAL_REVIEW_NO_AI, CLINICAL_REVIEW_PAGE, profile_needs_clinical_review
from app.security import token_user_id
from app.services.program_generator import NoProfile, PlanDay, WeeklyProgram, generate_for_user

router = APIRouter(prefix="/api")

WEEKS = 4
MAX_RANGE_DAYS = 62
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
NOTES_MAX = 2000
# "Today" is the server's UTC date (as in the Coach's progress tools). People west of UTC are never ahead of it;
# people east of it can be up to a day ahead, so a day counts as reachable up to one day after UTC today.
COMPLETE_GRACE_DAYS = 1
PARKING_DATE = "0000-01-01"     # a free slot for the middle of a swap (dates are UNIQUE per user)


def today() -> date:
    return datetime.now(timezone.utc).date()


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- plan -> calendar

def snapshot(plan: WeeklyProgram, day: PlanDay) -> dict:
    """What the day widget shows, frozen at creation so later generator changes can't rewrite it."""
    return {
        "plan_day": day.day,
        "focus": day.focus,
        "est_minutes": round(day.est_minutes, 1),
        "exercises": [e.model_dump() for e in day.exercises],
        "protocol_status": plan.protocol.status if plan.protocol else None,
        "review_notice": plan.protocol.review_notice if plan.protocol else None,
        "snapshot_at": now_utc(),
    }


def materialize_plan(user_id: int, start: date | None = None) -> dict:
    """Create (or refresh) 4 weeks of calendar entries from `start` (default today) for the user's current plan.
    Only untouched days dated `start` or later are replaced; see the module docstring."""
    start = start or today()
    days = [start + timedelta(days=i) for i in range(7 * WEEKS)]
    try:
        plan = generate_for_user(user_id)
    except NoProfile:
        return {"created": 0, "refreshed": 0, "kept": 0, "generated": False}
    by_weekday = {d.day: d for d in plan.days}
    conn = connect()
    try:
        with conn:
            refreshed = conn.execute(
                "DELETE FROM calendar_entries WHERE user_id = ? AND date >= ? AND completed = 0 "
                "AND (notes IS NULL OR TRIM(notes) = '')", (user_id, start.isoformat())).rowcount
            taken = {r[0] for r in conn.execute(
                "SELECT date FROM calendar_entries WHERE user_id = ? AND date BETWEEN ? AND ?",
                (user_id, days[0].isoformat(), days[-1].isoformat()))}
            created = 0
            if plan.generated:   # pregnant / postpartum: no plan, so nothing new is scheduled
                for d in days:
                    if d.isoformat() in taken:
                        continue   # a day the user completed or wrote on: keep it exactly as it is
                    pd = by_weekday[WEEKDAYS[d.weekday()]]
                    conn.execute(
                        "INSERT INTO calendar_entries (user_id, date, day_type, workout_content) VALUES (?, ?, ?, ?)",
                        (user_id, d.isoformat(), "workout" if pd.kind == "training" else "rest",
                         json.dumps(snapshot(plan, pd))))
                    created += 1
    finally:
        conn.close()
    return {"created": created, "refreshed": refreshed, "kept": len(taken), "generated": plan.generated}


# ---------------------------------------------------------------- reading

def signed_in(uid: int = Depends(token_user_id)) -> int:
    conn = connect()
    try:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (uid,)).fetchone():
            raise HTTPException(401, "Your sign-in is invalid or expired. Please sign in again.")
    finally:
        conn.close()
    return uid


def can_complete(day_type: str, day: str) -> bool:
    return day_type == "workout" and date.fromisoformat(day) <= today() + timedelta(days=COMPLETE_GRACE_DAYS)


def entry_dict(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"],
        "date": r["date"],
        "weekday": WEEKDAYS[date.fromisoformat(r["date"]).weekday()],
        "day_type": r["day_type"],
        "workout": json.loads(r["workout_content"]),
        "completed": bool(r["completed"]),
        "notes": r["notes"],
        "can_complete": can_complete(r["day_type"], r["date"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


@router.get("/calendar")
def get_calendar(
    start: date | None = Query(None, description="YYYY-MM-DD; default: Monday of this week"),
    end: date | None = Query(None, description="YYYY-MM-DD, inclusive; default: start + 6 days"),
    uid: int = Depends(signed_in),
) -> dict:
    start = start or today() - timedelta(days=today().weekday())
    end = end or start + timedelta(days=6)
    if end < start or (end - start).days >= MAX_RANGE_DAYS:
        raise HTTPException(422, f"end must be on or after start, at most {MAX_RANGE_DAYS} days in all.")
    base = {"start": start.isoformat(), "end": end.isoformat(), "today": today().isoformat()}

    if profile_needs_clinical_review(uid):   # no plan for them: an empty calendar, never stale workouts
        return {**base, "needs_quiz": False, "needs_clinical_review": True, "message": CLINICAL_REVIEW_NO_AI,
                "page": CLINICAL_REVIEW_PAGE, "entries": []}

    conn = connect()
    try:
        has_quiz = conn.execute("SELECT 1 FROM quiz_profiles WHERE user_id = ?", (uid,)).fetchone() is not None
        upcoming = conn.execute("SELECT COUNT(*) FROM calendar_entries WHERE user_id = ? AND date >= ?",
                                (uid, today().isoformat())).fetchone()[0]
    finally:
        conn.close()
    if has_quiz and not upcoming:   # accounts from before the calendar, or the 4 weeks ran out: top up
        materialize_plan(uid)

    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM calendar_entries WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date",
                            (uid, start.isoformat(), end.isoformat())).fetchall()
    finally:
        conn.close()
    return {**base, "needs_quiz": not has_quiz, "needs_clinical_review": False, "entries": [entry_dict(r) for r in rows]}


# ---------------------------------------------------------------- updating

class CalendarUpdate(BaseModel):
    model_config = {"extra": "forbid"}   # no user_id, day_type or workout_content from the client
    date: Day | None = None
    notes: str | None = Field(None, max_length=NOTES_MAX)
    completed: bool | None = None


def first_int(text: str) -> int | None:
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


TIMED = re.compile(r"\bhold\b|\bsec|\d\s*s\b")   # "24-30s hold", "30 sec", "45s"


def prescribed(sets: str, reps: str) -> tuple[int | None, int | None, int | None]:
    """(sets, reps, duration_seconds) for a log row, from the plan's ranges, using the low end of each.
    Holds become a duration (seconds per set x sets) instead of reps."""
    n_sets = first_int(str(sets))
    if TIMED.search(str(reps).lower()):
        return n_sets, None, (first_int(str(reps)) or 0) * (n_sets or 1)
    return n_sets, first_int(str(reps)), None


def log_rows(conn: sqlite3.Connection, uid: int, entry: sqlite3.Row) -> int:
    """One workout_logs row per planned exercise. These record the plan's prescription (the low end of the
    sets/reps range) as done; there's no weight, so the Coach's weight-lifted totals don't change.
    The note is NOT copied."""
    content = json.loads(entry["workout_content"])
    known = {r[0] for r in conn.execute("SELECT id FROM exercises")}
    n = 0
    for ex in content.get("exercises", []):
        sets, reps, seconds = prescribed(ex.get("sets", ""), ex.get("reps", ""))
        conn.execute(
            "INSERT INTO workout_logs (user_id, date, exercise_id, plan_day, sets, reps, duration_seconds,"
            " calendar_entry_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (uid, entry["date"], ex["exercise_id"] if ex.get("exercise_id") in known else None,
             content.get("plan_day"), sets, reps, seconds, entry["id"]))
        n += 1
    return n


@router.patch("/calendar/{entry_id}")
def update_entry(entry_id: int, body: CalendarUpdate, uid: int = Depends(signed_in)) -> dict:
    if profile_needs_clinical_review(uid):
        raise HTTPException(403, {"code": "needs_clinical_review", "message": CLINICAL_REVIEW_NO_AI,
                                  "page": CLINICAL_REVIEW_PAGE})
    sent = body.model_fields_set
    conn = connect()
    flagged: list[str] = []
    note_to_check: str | None = None
    swapped_with = None
    logged = removed = 0
    try:
        with conn:
            entry = conn.execute("SELECT * FROM calendar_entries WHERE id = ? AND user_id = ?",
                                 (entry_id, uid)).fetchone()
            if entry is None:   # someone else's entry looks exactly like a missing one
                raise HTTPException(404, "Calendar day not found.")
            stamp = now_utc()

            # 1. move (drag and drop). Onto a taken date = swap the two days.
            if "date" in sent and body.date is not None and body.date.isoformat() != entry["date"]:
                target = body.date.isoformat()
                if entry["completed"] or body.completed:
                    raise HTTPException(409, "This day is marked done, so it stays on its date. Un-mark it to move it.")
                other = conn.execute("SELECT * FROM calendar_entries WHERE user_id = ? AND date = ?",
                                     (uid, target)).fetchone()
                if other is not None and other["completed"]:
                    raise HTTPException(409, "That date already has a day marked done, so we can't swap onto it.")
                conn.execute("UPDATE calendar_entries SET date = ?, updated_at = ? WHERE id = ?",
                             (PARKING_DATE, stamp, entry_id))
                if other is not None:
                    conn.execute("UPDATE calendar_entries SET date = ?, updated_at = ? WHERE id = ?",
                                 (entry["date"], stamp, other["id"]))
                    swapped_with = other["id"]
                conn.execute("UPDATE calendar_entries SET date = ?, updated_at = ? WHERE id = ?",
                             (target, stamp, entry_id))

            # 2. notes: always saved. Checked for red flags below, after this transaction commits.
            if "notes" in sent:
                notes = (body.notes or "").strip() or None
                if notes != entry["notes"]:
                    conn.execute("UPDATE calendar_entries SET notes = ?, updated_at = ? WHERE id = ?",
                                 (notes, stamp, entry_id))
                    note_to_check = notes

            # 3. completed -> workout_logs (the same table the Coach reads)
            if "completed" in sent and body.completed is not None and body.completed != bool(entry["completed"]):
                current = conn.execute("SELECT * FROM calendar_entries WHERE id = ?", (entry_id,)).fetchone()
                if body.completed:
                    if current["day_type"] != "workout":
                        raise HTTPException(422, "Rest days don't get marked done. Resting is the point!")
                    if not can_complete(current["day_type"], current["date"]):
                        raise HTTPException(422, "You can mark a workout done on its day, not before.")
                    logged = log_rows(conn, uid, current)
                else:
                    removed = conn.execute("DELETE FROM workout_logs WHERE calendar_entry_id = ? AND user_id = ?",
                                           (entry_id, uid)).rowcount
                conn.execute("UPDATE calendar_entries SET completed = ?, updated_at = ? WHERE id = ?",
                             (int(body.completed), stamp, entry_id))
        row = conn.execute("SELECT * FROM calendar_entries WHERE id = ?", (entry_id,)).fetchone()
    finally:
        conn.close()

    # Red-flag check on the saved note: code only, never a model. The note stays saved either way.
    safety = {"flagged": False}
    if note_to_check:
        flagged = red_flags_in(note_to_check)
        if flagged:
            event_id = log_safety_event(uid, "calendar_note", note_to_check, "note_saved_pointed_to_professional")
            safety = {"flagged": True, "message": NOTE_SUPPORT_MESSAGE, "red_flags": flagged,
                      "safety_event_id": event_id}
    return {"entry": entry_dict(row), "swapped_with": swapped_with, "workout_logs_added": logged,
            "workout_logs_removed": removed, "safety": safety, "agent_called": False}

"""Calendar: the generated weekly plan laid out on real dates, movable and loggable.

Routes (sign-in required; the user always comes from the token):
  GET   /api/calendar?start=&end=   entries from start to end, inclusive (default: this Monday to Sunday)
  PATCH /api/calendar/{id}          {date?, notes?, completed?}

Rules, all enforced here in code:
  * materialize_plan() runs when the quiz is saved: 4 weeks of entries from today, one per date, following the
    plan's weekly pattern. Each entry's workout_content is a snapshot of that day of the plan.
    A retake REFRESHES only entries dated today or later that are not completed, have no notes, and are not
    custom. Past days, completed days, days with notes, and days the user built themselves are never touched.
  * Custom days: POST /api/calendar/{id}/custom (in app/agent_routes.py, with the other AI routes) builds a
    workout with the Workout Builder agent (same injury filter as always) and replaces that day's
    workout_content with it; source becomes 'custom' and the generated day is kept in planned_content.
    DELETE /api/calendar/{id}/custom restores it. Only for days that are today or later and not completed,
    and never for pregnant / postpartum users (403).
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
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.agents.safety import NOTE_SUPPORT_MESSAGE, log_safety_event, red_flags_in
from app.db import connect
from app.safety_rules import CLINICAL_REVIEW_NO_AI, CLINICAL_REVIEW_PAGE, profile_needs_clinical_review
from app.security import token_user_id
from app.services.program_generator import (NoProfile, PlanDay, WeeklyProgram, exercise_for_week, generate_for_user,
                                             progression_step)

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

MAX_AHEAD_DAYS = 182   # "Save to calendar" can extend the calendar this far (about 6 months)


def plan_week(day: date, started: date) -> int:
    """Week number of the plan on a date (week 1 = the 7 days from the day the plan started)."""
    return max(1, (day - started).days // 7 + 1)


def snapshot(plan: WeeklyProgram, day: PlanDay, on: date | None = None, started: date | None = None) -> dict:
    """What the day widget shows, frozen at creation so later generator changes can't rewrite it. With a date, the
    sets and reps are that week's (progressive overload; flat for injured / rehab profiles)."""
    enabled = bool(plan.progression and plan.progression.enabled)
    week = plan_week(on, started) if on and started else 1
    return {
        "plan_day": day.day,
        "focus": day.focus,
        "est_minutes": round(day.est_minutes, 1),
        "exercises": [exercise_for_week(e.model_dump(), week, enabled) for e in day.exercises],
        "week": week,
        "progression_step": progression_step(week, enabled),
        "protocol_status": plan.protocol.status if plan.protocol else None,
        "review_notice": plan.protocol.review_notice if plan.protocol else None,
        "snapshot_at": now_utc(),
    }


def open_day(on: date) -> dict:
    """A day with nothing planned yet ("I'll build it myself" mode, or a date opened for "Save to calendar")."""
    return {"plan_day": WEEKDAYS[on.weekday()], "focus": None, "est_minutes": 0, "exercises": [], "open": True,
            "protocol_status": None, "review_notice": None, "snapshot_at": now_utc()}


def calendar_settings(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT calendar_mode, plan_reviewed, plan_started_on FROM quiz_profiles WHERE user_id = ?",
                       (user_id,)).fetchone()
    if row is None:
        return None
    started = date.fromisoformat(row["plan_started_on"]) if row["plan_started_on"] else None
    if started is None:   # profiles from before plan_started_on: their first calendar day, else today
        first = conn.execute("SELECT MIN(date) FROM calendar_entries WHERE user_id = ?", (user_id,)).fetchone()[0]
        started = date.fromisoformat(first) if first else today()
    mode = row["calendar_mode"]
    return {"mode": mode, "reviewed": bool(row["plan_reviewed"]), "started": started,
            "review_pending": mode == "review" and not row["plan_reviewed"]}


def _fill(conn: sqlite3.Connection, user_id: int, dates: list[date], plan: WeeklyProgram | None, cfg: dict) -> int:
    """Create entries for the dates that don't have one, per the calendar mode. Never touches an existing entry."""
    if not dates:
        return 0
    taken = {r[0] for r in conn.execute(
        "SELECT date FROM calendar_entries WHERE user_id = ? AND date BETWEEN ? AND ?",
        (user_id, min(dates).isoformat(), max(dates).isoformat()))}
    by_weekday = {d.day: d for d in plan.days} if plan and plan.generated else {}
    created = 0
    for d in dates:
        if d.isoformat() in taken:
            continue   # a day the user completed, wrote on, or built: keep it exactly as it is
        if cfg["mode"] == "self":
            day_type, content = "rest", open_day(d)
        elif cfg["review_pending"] or not by_weekday:   # waiting for the review, or no plan (pregnant/postpartum)
            continue
        else:
            pd = by_weekday[WEEKDAYS[d.weekday()]]
            day_type = "workout" if pd.kind == "training" else "rest"
            content = snapshot(plan, pd, d, cfg["started"])
        conn.execute("INSERT INTO calendar_entries (user_id, date, day_type, workout_content) VALUES (?, ?, ?, ?)",
                     (user_id, d.isoformat(), day_type, json.dumps(content)))
        created += 1
    return created


def materialize_plan(user_id: int, start: date | None = None) -> dict:
    """Create (or refresh) 4 weeks of calendar entries from `start` (default today) for the user's current plan and
    calendar mode. Only untouched days dated `start` or later are replaced; see the module docstring."""
    start = start or today()
    days = [start + timedelta(days=i) for i in range(7 * WEEKS)]
    try:
        plan = generate_for_user(user_id)
    except NoProfile:
        return {"created": 0, "refreshed": 0, "kept": 0, "generated": False}
    conn = connect()
    try:
        with conn:
            cfg = calendar_settings(conn, user_id)
            refreshed = conn.execute(
                "DELETE FROM calendar_entries WHERE user_id = ? AND date >= ? AND completed = 0 "
                "AND (notes IS NULL OR TRIM(notes) = '') AND source = 'generated'", (user_id, start.isoformat())).rowcount
            kept = conn.execute("SELECT COUNT(*) FROM calendar_entries WHERE user_id = ? AND date BETWEEN ? AND ?",
                                (user_id, days[0].isoformat(), days[-1].isoformat())).fetchone()[0]
            created = _fill(conn, user_id, days, plan, cfg)
    finally:
        conn.close()
    return {"created": created, "refreshed": refreshed, "kept": kept, "generated": plan.generated, "mode": cfg["mode"]}


def ensure_through(user_id: int, target: date) -> int:
    """Lay out every missing day from today through `target` (per the calendar mode), and make sure `target` itself
    has an entry to hold a workout (an open day if the mode wouldn't create one, e.g. review not finished yet)."""
    plan = generate_for_user(user_id)
    conn = connect()
    try:
        with conn:
            cfg = calendar_settings(conn, user_id)
            n = (target - today()).days
            created = _fill(conn, user_id, [today() + timedelta(days=i) for i in range(n + 1)], plan, cfg)
            if not conn.execute("SELECT 1 FROM calendar_entries WHERE user_id = ? AND date = ?",
                                (user_id, target.isoformat())).fetchone():
                conn.execute("INSERT INTO calendar_entries (user_id, date, day_type, workout_content) VALUES (?, ?, ?, ?)",
                             (user_id, target.isoformat(), "rest", json.dumps(open_day(target))))
                created += 1
    finally:
        conn.close()
    return created


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


def can_override(day: str, completed: bool) -> bool:
    return not completed and date.fromisoformat(day) >= today()


def entry_dict(r: sqlite3.Row) -> dict:
    planned = json.loads(r["planned_content"]) if r["planned_content"] else None
    return {
        "id": r["id"],
        "date": r["date"],
        "weekday": WEEKDAYS[date.fromisoformat(r["date"]).weekday()],
        "day_type": r["day_type"],
        "workout": json.loads(r["workout_content"]),
        "completed": bool(r["completed"]),
        "notes": r["notes"],
        "can_complete": can_complete(r["day_type"], r["date"]),
        "source": r["source"],   # 'generated' (from the plan) or 'custom' (built by the user)
        "can_override": can_override(r["date"], bool(r["completed"])),
        # What "Revert to planned workout" would bring back (only on custom days).
        "planned": {"day_type": planned["day_type"], "focus": planned["workout_content"].get("focus")} if planned else None,
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

    from app.cardio import cardio_logs_between   # local import: cardio imports this module
    base["cardio"] = cardio_logs_between(uid, start, end)   # the user's own activity log, shown in every case

    if profile_needs_clinical_review(uid):   # no plan for them: an empty calendar, never stale workouts
        return {**base, "needs_quiz": False, "needs_clinical_review": True, "message": CLINICAL_REVIEW_NO_AI,
                "page": CLINICAL_REVIEW_PAGE, "entries": [], "calendar_mode": None, "needs_review": False}

    conn = connect()
    try:
        has_quiz = conn.execute("SELECT 1 FROM quiz_profiles WHERE user_id = ?", (uid,)).fetchone() is not None
        upcoming = conn.execute("SELECT COUNT(*) FROM calendar_entries WHERE user_id = ? AND date >= ?",
                                (uid, today().isoformat())).fetchone()[0]
        cfg = calendar_settings(conn, uid)
    finally:
        conn.close()
    base.update(calendar_mode=cfg["mode"] if cfg else None, needs_review=bool(cfg and cfg["review_pending"]))
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


# ---------------------------------------------------------------- custom days (override + revert)

def _overridable(conn: sqlite3.Connection, uid: int, entry_id: int) -> sqlite3.Row:
    entry = conn.execute("SELECT * FROM calendar_entries WHERE id = ? AND user_id = ?", (entry_id, uid)).fetchone()
    if entry is None:
        raise HTTPException(404, "Calendar day not found.")
    if entry["completed"]:
        raise HTTPException(409, "This day is marked done, so it stays as it was. Un-mark it to change it.")
    if date.fromisoformat(entry["date"]) < today():
        raise HTTPException(422, "Past days can't be changed.")
    return entry


def check_overridable(uid: int, entry_id: int) -> None:
    """Called BEFORE the Workout Builder runs, so an ineligible day never costs a model call."""
    conn = connect()
    try:
        _overridable(conn, uid, entry_id)
    finally:
        conn.close()


def custom_content(session: dict, request: dict, weekday: str) -> dict:
    """The Workout Builder's session in the same shape as a generated day, so the widget, the done toggle and the
    workout_logs rows all work unchanged."""
    groups = ", ".join(g.replace("_", " ") for g in request["picks"])
    return {
        "plan_day": weekday,
        "focus": f"Your own: {groups}",
        "est_minutes": session["total_estimated_minutes"],
        "exercises": [{"exercise_id": x["exercise_id"], "name": x["name"], "muscle_group": x["muscle_group"],
                       "sets": str(x["sets"]), "reps": x["reps"], "rest_seconds": x["rest_seconds"],
                       "est_minutes": x["est_minutes"], "injury_check": x["injury_check"]}
                      for x in session["exercises"]],
        "built_by": "workout_builder",
        "request": request,
        "balance_note": session.get("balance_note"),
        "notes": session.get("notes", []),
        "protocol_status": None,
        "review_notice": None,
        "snapshot_at": now_utc(),
    }


def apply_custom(uid: int, entry_id: int, session: dict, request: dict) -> dict:
    """Replace the day's workout with the custom session, keeping the generated day for revert."""
    if not session["exercises"]:
        raise HTTPException(422, "We couldn't fit any exercises with those picks, your equipment and your injury "
                                 "filters, so this day wasn't changed. Try other muscle groups.")
    conn = connect()
    try:
        with conn:
            entry = _overridable(conn, uid, entry_id)   # checked again: the day may have changed while the AI ran
            weekday = WEEKDAYS[date.fromisoformat(entry["date"]).weekday()]
            planned = entry["planned_content"]
            if entry["source"] == "generated":          # first override: keep what the plan had
                planned = json.dumps({"day_type": entry["day_type"],
                                      "workout_content": json.loads(entry["workout_content"])})
            conn.execute(
                "UPDATE calendar_entries SET day_type = 'workout', workout_content = ?, source = 'custom', "
                "planned_content = ?, updated_at = ? WHERE id = ?",
                (json.dumps(custom_content(session, request, weekday)), planned, now_utc(), entry_id))
        row = conn.execute("SELECT * FROM calendar_entries WHERE id = ?", (entry_id,)).fetchone()
    finally:
        conn.close()
    return entry_dict(row)


@router.delete("/calendar/{entry_id}/custom")
def revert_custom(entry_id: int, uid: int = Depends(signed_in)) -> dict:
    """Undo an override: the generated day comes back exactly as it was. No AI involved."""
    if profile_needs_clinical_review(uid):
        raise HTTPException(403, {"code": "needs_clinical_review", "message": CLINICAL_REVIEW_NO_AI,
                                  "page": CLINICAL_REVIEW_PAGE})
    conn = connect()
    try:
        with conn:
            entry = _overridable(conn, uid, entry_id)
            if entry["source"] != "custom":
                raise HTTPException(409, "This day is already the planned workout.")
            planned = json.loads(entry["planned_content"])
            conn.execute(
                "UPDATE calendar_entries SET day_type = ?, workout_content = ?, source = 'generated', "
                "planned_content = NULL, updated_at = ? WHERE id = ?",
                (planned["day_type"], json.dumps(planned["workout_content"]), now_utc(), entry_id))
        row = conn.execute("SELECT * FROM calendar_entries WHERE id = ?", (entry_id,)).fetchone()
    finally:
        conn.close()
    return {"entry": entry_dict(row)}


def custom_day_items(uid: int, entry_id: int) -> list[dict]:
    """The exercises of a day the user built (for the Workout Reviewer). 404 if it isn't theirs, 409 if it's a
    generated day: reviews are for workouts people build themselves."""
    conn = connect()
    try:
        entry = conn.execute("SELECT * FROM calendar_entries WHERE id = ? AND user_id = ?", (entry_id, uid)).fetchone()
    finally:
        conn.close()
    if entry is None:
        raise HTTPException(404, "Calendar day not found.")
    if entry["source"] != "custom":
        raise HTTPException(409, "Reviews are for workouts you build yourself. Build your own for this day first.")
    return [{"exercise_id": x["exercise_id"], "est_minutes": x["est_minutes"]}
            for x in json.loads(entry["workout_content"])["exercises"]]


# ---------------------------------------------------------------- how the calendar is filled (the mode)

CalendarMode = Literal["generated", "review", "self"]


class ModeIn(BaseModel):
    model_config = {"extra": "forbid"}
    mode: CalendarMode


def _clinical_block(uid: int) -> None:
    if profile_needs_clinical_review(uid):
        raise HTTPException(403, {"code": "needs_clinical_review", "message": CLINICAL_REVIEW_NO_AI,
                                  "page": CLINICAL_REVIEW_PAGE})


@router.put("/calendar/mode")
def set_mode(body: ModeIn, uid: int = Depends(signed_in)) -> dict:
    """generated: the quiz plan on the calendar. review: the quiz plan, laid out only after the user reviews it.
    self: open days the user fills with Build Your Own. Untouched future days are re-laid out to match; days the
    user completed, wrote on or built are kept, as always."""
    conn = connect()
    try:
        with conn:
            n = conn.execute("UPDATE quiz_profiles SET calendar_mode = ?, plan_reviewed = 0 WHERE user_id = ?",
                             (body.mode, uid)).rowcount
    finally:
        conn.close()
    if not n:
        raise HTTPException(409, "Take the quiz first.")
    result = materialize_plan(uid)
    return {"calendar_mode": body.mode, "needs_review": body.mode == "review", "laid_out": result["created"]}


class ReviewIn(BaseModel):
    model_config = {"extra": "forbid"}
    swaps: dict[str, str] = Field(default_factory=dict, max_length=60)   # {generated exercise id: replacement id}


@router.get("/calendar/review")
def get_review(uid: int = Depends(signed_in)) -> dict:
    """The generated plan with, for every exercise, what it may be swapped for (same safety filters)."""
    _clinical_block(uid)
    try:
        plan = generate_for_user(uid, with_swap_options=True)
    except NoProfile as e:
        raise HTTPException(409, str(e)) from e
    conn = connect()
    try:
        cfg = calendar_settings(conn, uid)
        swaps = json.loads(conn.execute("SELECT plan_swaps FROM quiz_profiles WHERE user_id = ?", (uid,)).fetchone()[0])
    finally:
        conn.close()
    return {"plan": plan.model_dump(), "swaps": swaps, "calendar_mode": cfg["mode"], "reviewed": cfg["reviewed"]}


@router.post("/calendar/review")
def finalize_review(body: ReviewIn, uid: int = Depends(signed_in)) -> dict:
    """Save the swaps and lay the reviewed plan out on the calendar. Every replacement must be one of the options
    the safety filters allow for that exercise (422 otherwise), and it's checked again whenever the plan is built."""
    _clinical_block(uid)
    try:
        options = generate_for_user(uid, with_swap_options=True).swap_options or {}
    except NoProfile as e:
        raise HTTPException(409, str(e)) from e
    bad = [f"{a} -> {b}" for a, b in body.swaps.items()
           if a not in options or b not in {o["id"] for o in options[a]}]
    if bad:
        raise HTTPException(422, f"Not an allowed swap for this plan: {bad}.")
    conn = connect()
    try:
        with conn:
            conn.execute("UPDATE quiz_profiles SET plan_swaps = ?, plan_reviewed = 1 WHERE user_id = ?",
                         (json.dumps(body.swaps), uid))
    finally:
        conn.close()
    result = materialize_plan(uid)
    return {"swaps": body.swaps, "laid_out": result["created"]}


# ---------------------------------------------------------------- Build Your Own -> calendar ("Save to calendar")

BUILT_KEEP_DAYS = 7


def store_built(uid: int, request: dict, session: dict) -> int:
    """Remember a session exactly as the Workout Builder made it (and drop this user's old ones)."""
    conn = connect()
    try:
        with conn:
            conn.execute("DELETE FROM built_workouts WHERE user_id = ? AND created_at < ?",
                         (uid, (datetime.now(timezone.utc) - timedelta(days=BUILT_KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")))
            return conn.execute("INSERT INTO built_workouts (user_id, request, session) VALUES (?, ?, ?)",
                                (uid, json.dumps(request), json.dumps(session))).lastrowid
    finally:
        conn.close()


class SaveBuiltIn(BaseModel):
    model_config = {"extra": "forbid"}   # no exercises from the client: only the id of a session the server built
    built_id: int
    date: Day


@router.post("/calendar/save-built")
def save_built(body: SaveBuiltIn, uid: int = Depends(signed_in)) -> dict:
    """A second way into the custom-day mechanism: put a session built on the Build Your Own page onto a calendar
    day. Same apply_custom as "Build your own for this day" (source 'custom', kept on retake, revertible). If the
    date isn't laid out yet, the calendar is extended to it."""
    _clinical_block(uid)
    if body.date < today():
        raise HTTPException(422, "Past days can't be changed.")
    if (body.date - today()).days > MAX_AHEAD_DAYS:
        raise HTTPException(422, f"Pick a date within the next {MAX_AHEAD_DAYS // 30} months.")
    conn = connect()
    try:
        row = conn.execute("SELECT request, session FROM built_workouts WHERE id = ? AND user_id = ?",
                           (body.built_id, uid)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(404, "That workout isn't available any more. Build it again, then save it.")
    try:
        extended = ensure_through(uid, body.date)
    except NoProfile as e:
        raise HTTPException(409, str(e)) from e
    conn = connect()
    try:
        entry_id = conn.execute("SELECT id FROM calendar_entries WHERE user_id = ? AND date = ?",
                                (uid, body.date.isoformat())).fetchone()[0]
    finally:
        conn.close()
    entry = apply_custom(uid, entry_id, json.loads(row["session"]), json.loads(row["request"]))
    return {"entry": entry, "days_added": extended}


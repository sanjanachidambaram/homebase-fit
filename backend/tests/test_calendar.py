"""The calendar: the plan on real dates, the retake preservation rule, drag-and-drop, logging, and its safety rules.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_calendar.py -v

"Today" is frozen per test (app.calendar.today) so dates are predictable. No test calls a real model.
"""

import json
from datetime import date, timedelta

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app import calendar
from app.agents import harness
from app.agents.safety import NOTE_SUPPORT_MESSAGE
from app.db import connect
from app.mcp_server.progress import check_goal_achievement, get_progress_summary
from app.services.program_generator import generate_for_user
from tests.helpers import quiz_answers
from tests.test_agents import rows, use_script  # noqa: F401  (use_script is a fixture)

MONDAY = date(2026, 10, 19)
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
RED_FLAG_NOTE = "Had a sharp pain in my knee on the last set of squats"
SENTINEL = "ZEBRA-PRIVATE-NOTE-7731"


@pytest.fixture
def on_day(monkeypatch):
    """Freeze the calendar's "today". Call it again to move time forward."""
    def set_today(d: date):
        monkeypatch.setattr(calendar, "today", lambda: d)
        return d
    set_today(MONDAY)
    return set_today


def account(client, email, **answers) -> tuple[int, dict]:
    r = client.post("/api/users", json={"email": email, "password": "correct horse 1"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    retake(client, r["user_id"], h, **answers)
    return r["user_id"], h


def retake(client, uid, h, **answers):
    r = client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "test", "answers": quiz_answers(**answers)})
    assert r.status_code == 200, r.text


def get_days(client, h, start=MONDAY, end=MONDAY + timedelta(days=27)) -> dict:
    r = client.get("/api/calendar", headers=h, params={"start": start.isoformat(), "end": end.isoformat()})
    assert r.status_code == 200, r.text
    return r.json()


def by_date(body: dict) -> dict[str, dict]:
    return {e["date"]: e for e in body["entries"]}


def stored(e: dict) -> dict:
    """An entry without the flags computed from "today" (tests move today forward)."""
    return {k: v for k, v in e.items() if k not in ("can_override", "can_complete")}


def patch(client, h, entry_id, **body):
    return client.patch(f"/api/calendar/{entry_id}", headers=h, json=body)


def d(offset: int) -> str:
    return (MONDAY + timedelta(days=offset)).isoformat()


# ================================================================ materializing the plan

def test_quiz_lays_out_four_weeks_of_the_plan(client, on_day):
    uid, h = account(client, "cal@example.com")
    plan = {p.day: p for p in generate_for_user(uid).days}
    entries = get_days(client, h)["entries"]
    assert len(entries) == 28 and [e["date"] for e in entries] == [d(i) for i in range(28)]
    for e in entries:
        planned = plan[e["weekday"]]
        assert e["day_type"] == ("workout" if planned.kind == "training" else "rest")
        assert [x["exercise_id"] for x in e["workout"]["exercises"]] == [x.exercise_id for x in planned.exercises]
        assert e["completed"] is False and e["notes"] is None
    workout_days = {e["weekday"] for e in entries if e["day_type"] == "workout"}
    assert workout_days == {"mon", "wed", "fri"}          # beginner weight loss + rehab: 3 days a week
    assert get_days(client, h, MONDAY + timedelta(days=28), MONDAY + timedelta(days=34))["entries"] == []


def test_snapshot_does_not_change_when_the_content_changes_later(client, on_day):
    uid, h = account(client, "snap@example.com")
    first = by_date(get_days(client, h))[d(0)]["workout"]["exercises"][0]
    conn = connect()
    with conn:
        conn.execute("UPDATE exercises SET name = 'Renamed Later' WHERE id = ?", (first["exercise_id"],))
    conn.close()
    assert by_date(get_days(client, h))[d(0)]["workout"]["exercises"][0]["name"] == first["name"]


# ================================================================ the retake preservation rule

def test_retake_keeps_logged_and_noted_days_and_refreshes_only_untouched_future_days(client, on_day):
    uid, h = account(client, "retake@example.com")
    before = by_date(get_days(client, h))
    logged, noted, past_untouched = before[d(0)], before[d(4)], before[d(1)]   # Mon (workout), Fri, Tue
    assert logged["day_type"] == "workout"
    assert patch(client, h, logged["id"], completed=True).status_code == 200
    assert patch(client, h, noted["id"], notes="Busy day, keep it short").status_code == 200
    logs_before = rows("SELECT * FROM workout_logs WHERE calendar_entry_id = ?", logged["id"])
    assert logs_before

    on_day(MONDAY + timedelta(days=2))                       # Wednesday: Mon and Tue are now in the past
    retake(client, uid, h, goals=["strength"], experience_level="advanced", days_available=6)
    new_plan = {p.day: p for p in generate_for_user(uid).days}
    old_pattern = {e["weekday"] for e in before.values() if e["day_type"] == "workout"}
    new_pattern = {k for k, p in new_plan.items() if p.kind == "training"}
    assert old_pattern != new_pattern, "the retake should produce a different weekly pattern"

    after = by_date(get_days(client, h, MONDAY, MONDAY + timedelta(days=29)))
    # the logged day: same row, same snapshot, still done, and its workout_logs untouched
    assert stored(after[d(0)]) == stored({**logged, "completed": True, "updated_at": after[d(0)]["updated_at"]})
    assert rows("SELECT * FROM workout_logs WHERE calendar_entry_id = ?", logged["id"]) == logs_before
    # the day with notes: same row, same (old) workout, notes intact, even though it's in the future
    assert after[d(4)]["id"] == noted["id"] and after[d(4)]["workout"] == noted["workout"]
    assert after[d(4)]["notes"] == "Busy day, keep it short"
    # past days are history: never refreshed, even untouched ones
    assert stored(after[d(1)]) == stored(past_untouched)
    # every other day from today on was rebuilt from the NEW plan, for 4 weeks from the new today
    for i in range(2, 30):
        e = after[d(i)]
        if i == 4:
            continue
        assert e["id"] not in {x["id"] for x in before.values()}, d(i)
        planned = new_plan[e["weekday"]]
        assert e["day_type"] == ("workout" if planned.kind == "training" else "rest"), d(i)
        assert [x["exercise_id"] for x in e["workout"]["exercises"]] == [x.exercise_id for x in planned.exercises]
    assert len(after) == 30                                   # Mon 10-19 .. Tue 11-17: one entry per date


# ================================================================ drag and drop (PATCH date)

def test_moving_a_day_onto_another_swaps_them(client, on_day):
    uid, h = account(client, "drag@example.com")
    days = by_date(get_days(client, h))
    mon, tue = days[d(0)], days[d(1)]
    assert (mon["day_type"], tue["day_type"]) == ("workout", "rest")
    r = patch(client, h, mon["id"], date=d(1))
    assert r.status_code == 200, r.text
    assert r.json()["swapped_with"] == tue["id"] and r.json()["entry"]["date"] == d(1)
    days = by_date(get_days(client, h))
    assert (days[d(0)]["id"], days[d(0)]["day_type"]) == (tue["id"], "rest")
    assert (days[d(1)]["id"], days[d(1)]["day_type"]) == (mon["id"], "workout")
    assert days[d(1)]["workout"] == mon["workout"]            # the workout moved with it, unchanged

    far = "2027-01-04"                                        # an empty date: a plain move
    assert patch(client, h, mon["id"], date=far).json()["swapped_with"] is None
    assert rows("SELECT date FROM calendar_entries WHERE id = ?", mon["id"]) == [{"date": far}]


def test_done_days_stay_put(client, on_day):
    uid, h = account(client, "stay@example.com")
    days = by_date(get_days(client, h))
    assert patch(client, h, days[d(0)]["id"], completed=True).status_code == 200
    assert patch(client, h, days[d(0)]["id"], date=d(3)).status_code == 409        # can't move a done day
    assert patch(client, h, days[d(1)]["id"], date=d(0)).status_code == 409        # or swap onto one
    assert by_date(get_days(client, h))[d(0)]["id"] == days[d(0)]["id"]


# ================================================================ completed -> workout_logs

def test_completing_a_day_writes_the_workout_logs_the_coach_reads(client, on_day):
    uid, h = account(client, "done@example.com")
    days = by_date(get_days(client, h))
    mon = days[d(0)]
    patch(client, h, mon["id"], notes="felt strong today")
    r = patch(client, h, mon["id"], completed=True).json()
    assert r["workout_logs_added"] == len(mon["workout"]["exercises"]) > 0
    logs = rows("SELECT * FROM workout_logs WHERE user_id = ?", uid)
    assert {(l["date"], l["calendar_entry_id"], l["plan_day"]) for l in logs} == {(d(0), mon["id"], "mon")}
    assert all(l["notes"] is None for l in logs)              # the calendar note is not copied
    assert [l["exercise_id"] for l in logs] == [x["exercise_id"] for x in mon["workout"]["exercises"]]

    summary = get_progress_summary(uid, MONDAY)
    assert summary["sessions_logged"] == 1 and summary["current_streak_days"] == 1

    assert patch(client, h, mon["id"], completed=False).json()["workout_logs_removed"] == len(logs)
    assert rows("SELECT COUNT(*) AS n FROM workout_logs WHERE user_id = ?", uid) == [{"n": 0}]


@pytest.mark.parametrize("sets, reps, expected", [
    ("1-2", "12-15", (1, 12, None)), ("3", "8 each side", (3, 8, None)),
    ("1-2", "24-30s hold", (1, None, 24)), ("2", "30 sec", (2, None, 60)), ("2-3", "45s", (2, None, 90)),
])
def test_logged_rows_use_the_low_end_and_turn_holds_into_seconds(sets, reps, expected):
    assert calendar.prescribed(sets, reps) == expected


def test_rest_days_and_future_days_cant_be_marked_done(client, on_day):
    uid, h = account(client, "rules@example.com")
    days = by_date(get_days(client, h))
    assert patch(client, h, days[d(1)]["id"], completed=True).status_code == 422   # rest day
    assert patch(client, h, days[d(2)]["id"], completed=True).status_code == 422   # Wednesday, two days ahead
    assert days[d(2)]["can_complete"] is False and days[d(0)]["can_complete"] is True
    assert rows("SELECT COUNT(*) AS n FROM workout_logs WHERE user_id = ?", uid) == [{"n": 0}]


# ================================================================ safety: notes

def test_red_flag_note_is_saved_logged_and_answered_without_ai(client, on_day, use_script):
    script = use_script(("final", {"encouragement": "x", "fun_fact_comparison": None}))
    uid, h = account(client, "note@example.com")
    entry = by_date(get_days(client, h))[d(0)]

    r = patch(client, h, entry["id"], notes=RED_FLAG_NOTE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["entry"]["notes"] == RED_FLAG_NOTE                       # saved: it's their log
    assert body["safety"]["flagged"] is True and body["safety"]["message"] == NOTE_SUPPORT_MESSAGE
    assert "sharp/severe pain" in body["safety"]["red_flags"] and body["agent_called"] is False
    events = rows("SELECT * FROM safety_events WHERE user_id = ?", uid)
    assert [(e["source"], e["trigger_text"], e["action_taken"]) for e in events] == \
        [("calendar_note", RED_FLAG_NOTE, "note_saved_pointed_to_professional")]
    assert body["safety"]["safety_event_id"] == events[0]["id"]
    assert script.calls == 0 and rows("SELECT COUNT(*) AS n FROM agent_runs") == [{"n": 0}]

    # saving the same note again doesn't log it twice; an ordinary note logs nothing
    assert patch(client, h, entry["id"], notes=RED_FLAG_NOTE).json()["safety"] == {"flagged": False}
    other = by_date(get_days(client, h))[d(2)]
    assert patch(client, h, other["id"], notes="Great session, added a set").json()["safety"] == {"flagged": False}
    assert len(rows("SELECT * FROM safety_events WHERE user_id = ?", uid)) == 1


class Recorder:
    """A fake model that records EVERYTHING it is sent (prompts, instructions, tool results) and plays a script."""

    def __init__(self, *steps):
        self.steps, self.seen = list(steps), []

    def model(self) -> FunctionModel:
        def fn(messages, info: AgentInfo) -> ModelResponse:
            self.seen.append(repr(messages))
            step = sum(isinstance(m, ModelResponse) for m in messages)
            name, args = self.steps[min(step, len(self.steps) - 1)]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name if name == "final" else name, args)])
        return FunctionModel(fn)


def test_calendar_notes_never_reach_any_model(client, on_day, monkeypatch):
    """Same boundary as injury_notes: the user's own words stay in the database. We write a unique note on
    several days (one of them completed), then run every agent with a fake model that records everything it
    is sent, and call the MCP tools that read user activity directly."""
    uid, h = account(client, "private.notes@example.com")
    days = by_date(get_days(client, h))
    for i in (0, 2, 4):
        assert patch(client, h, days[d(i)]["id"], notes=f"{SENTINEL} day {i}").status_code == 200
    assert patch(client, h, days[d(0)]["id"], completed=True).status_code == 200

    sent = []
    for method, route, body, steps in [
        ("GET", "/api/coach/summary", None, [("get_progress_summary", {}), ("check_goal_achievement", {}),
                                              ("final", {"encouragement": "Nice!", "fun_fact_comparison": None})]),
        ("POST", "/api/programs/recommend", {}, [("final", {"explanation": "A gentle plan."})]),
        ("POST", "/api/workouts/build", {"picks": {"core": 1}, "time_budget_minutes": 10},
         [("final", {"items": [], "balance_note": "-"})]),
        ("POST", "/api/basics/ask", {"question": "How long should I rest between sets?"},
         [("final", {"answered": False, "answer": "-", "source_slugs": []})]),
    ]:
        rec = Recorder(*steps)
        monkeypatch.setattr(harness, "get_model", rec.model)
        client.request(method, route, json=body, headers=h)
        assert rec.seen, f"{route}: the fake model should have been called"
        sent += rec.seen
    everything = " ".join(sent)
    assert "check_goal_achievement" in everything and "plan_workouts_completed" in everything   # tools ran
    assert SENTINEL not in everything

    for result in (get_progress_summary(uid, MONDAY), check_goal_achievement(uid, MONDAY)):
        assert SENTINEL not in json.dumps(result)


# ================================================================ pregnant / postpartum

def test_pregnant_users_get_an_empty_calendar_pointing_to_support(client, on_day):
    uid, h = account(client, "was-not@example.com")
    days = by_date(get_days(client, h))
    patch(client, h, days[d(3)]["id"], notes="my own note")
    retake(client, uid, h, pregnancy_status="pregnant")

    body = get_days(client, h)
    assert body["needs_clinical_review"] is True and body["entries"] == [] and body["page"] == "/pregnancy-support"
    # no stale workouts left behind; their own note is kept (their data), just not shown or used
    assert rows("SELECT notes FROM calendar_entries WHERE user_id = ?", uid) == [{"notes": "my own note"}]
    assert patch(client, h, days[d(3)]["id"], notes="x").status_code == 403

    new_uid, nh = account(client, "pp@example.com", pregnancy_status="postpartum")
    assert get_days(client, nh)["entries"] == []
    assert rows("SELECT COUNT(*) AS n FROM calendar_entries WHERE user_id = ?", new_uid) == [{"n": 0}]


# ================================================================ access, input, and the goal check

def test_users_only_ever_see_and_change_their_own_days(client, on_day):
    a, ha = account(client, "a@example.com")
    b, hb = account(client, "b@example.com")
    a_day = by_date(get_days(client, ha))[d(0)]
    assert patch(client, hb, a_day["id"], notes="hi").status_code == 404
    assert patch(client, hb, a_day["id"], date=d(1)).status_code == 404
    assert {e["id"] for e in get_days(client, hb)["entries"]}.isdisjoint({e["id"] for e in get_days(client, ha)["entries"]})
    assert patch(client, ha, a_day["id"], user_id=b).status_code == 422
    assert patch(client, ha, a_day["id"], workout_content={}).status_code == 422
    assert client.get("/api/calendar").status_code == 401
    assert client.get("/api/calendar", headers=ha, params={"start": d(5), "end": d(0)}).status_code == 422


def test_quizless_account_gets_a_take_the_quiz_state(client, on_day):
    r = client.post("/api/users", json={"email": "noquiz@example.com", "password": "correct horse 1"}).json()
    body = get_days(client, {"Authorization": f"Bearer {r['token']}"})
    assert body["needs_quiz"] is True and body["entries"] == []


def test_goal_check_compares_completed_days_with_the_plan(client, on_day):
    uid, h = account(client, "goal@example.com")
    today = MONDAY + timedelta(days=13)                      # two weeks in; the quiz "was taken" on MONDAY
    conn = connect()
    with conn:
        conn.execute("UPDATE quiz_profiles SET created_at = ? WHERE user_id = ?", (MONDAY.isoformat() + "T08:00:00Z", uid))
    conn.close()
    on_day(today)
    days = by_date(get_days(client, h, MONDAY, today))
    workouts = [e for e in days.values() if e["day_type"] == "workout"]     # Mon/Wed/Fri x 2 = 6
    assert len(workouts) == 6
    for e in workouts[:2]:
        assert patch(client, h, e["id"], completed=True).status_code == 200

    result = check_goal_achievement(uid, today)
    assert (result["progress"]["plan_workouts_scheduled"], result["progress"]["plan_workouts_completed"]) == (6, 2)
    adherence = next(c for c in result["checks"] if c["check"] == "plan_adherence")
    assert adherence == {"check": "plan_adherence", "status": "behind", "detail": "2 of 6 planned workout days marked done"}

    for e in workouts[2:]:
        patch(client, h, e["id"], completed=True)
    adherence = next(c for c in check_goal_achievement(uid, today)["checks"] if c["check"] == "plan_adherence")
    assert adherence["status"] == "on_track" and adherence["detail"].startswith("6 of 6")

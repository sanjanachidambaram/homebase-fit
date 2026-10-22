"""Workout Reviewer: coverage and the estimate are computed by code; the model only narrates them.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_workout_review.py -v

The headline guarantee (shared_rules.md rule 7) is tested directly: whatever the model writes, the reply the
user sees never contains a number that isn't in the code's own output.
"""

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agents import harness
from app.agents.workout_reviewer import numbers_in, plain_summary, review_for_model
from app.db import connect
from app.services import workout_review as wr
from tests.test_agents import rows, use_script  # noqa: F401  (fixture)
from tests.test_calendar import account, by_date, d, get_days, on_day, retake  # noqa: F401
from tests.test_calendar_custom import CORE_SCRIPT

ITEMS = [{"exercise_id": "dead_bug", "sets": 2, "reps": "8 each side", "rest_seconds": 30},
         {"exercise_id": "incline_pushup", "sets": 2, "reps": "10", "rest_seconds": 30},
         {"exercise_id": "bodyweight_squat", "sets": 2, "reps": "12", "rest_seconds": 30}]


def session(*ids) -> list[dict]:
    conn = connect()
    try:
        found = {r["id"]: dict(r) for r in conn.execute(
            f"SELECT id AS exercise_id, name, muscle_group, force, id FROM exercises WHERE id IN ({','.join('?' for _ in ids)})",
            ids)}
    finally:
        conn.close()
    return [found[i] for i in ids]


class Narrator:
    """Fake model: answers with the given summaries in turn and records exactly what it was sent."""

    def __init__(self, *summaries):
        self.summaries, self.calls, self.seen = list(summaries), 0, []

    def model(self) -> FunctionModel:
        def fn(messages, info: AgentInfo) -> ModelResponse:
            self.calls += 1
            self.seen.append(repr(messages))
            text = self.summaries[min(self.calls - 1, len(self.summaries) - 1)]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"summary": text})])
        return FunctionModel(fn)


@pytest.fixture
def narrator(monkeypatch):
    def install(*summaries) -> Narrator:
        n = Narrator(*summaries)
        monkeypatch.setattr(harness, "get_model", n.model)
        return n
    return install


def review_api(client, h, items=ITEMS):
    return client.post("/api/workouts/review", headers=h, json={"items": items})


# ================================================================ 1. coverage (pure code)

def test_coverage_all_pushing_and_missing_groups(test_db):
    c = wr.coverage(session("bodyweight_squat", "incline_pushup", "chair_triceps_dip", "dead_bug"))
    assert c["groups_hit"] == [{"group": "legs", "exercises": 1}, {"group": "arms", "exercises": 2},
                               {"group": "core", "exercises": 1}]
    assert c["groups_missing"] == ["back", "chest", "shoulders"]
    assert c["upper_body_balance"] == {"push": 2, "pull": 0, "static": 0, "unclassified": 0,
                                       "note": "No pull exercises: the upper-body work is all pushing (2 push)."}
    assert c["notes"] == ["Back, chest and shoulders weren't included."]


def test_coverage_mostly_pulling_balanced_and_no_upper_body(test_db):
    mostly = wr.coverage(session("band_pull_apart", "band_biceps_curl", "knee_pushup", "forearm_plank", "glute_bridge"))
    assert mostly["upper_body_balance"]["note"] == "Mostly pulling (1 push, 2 pull)."
    assert mostly["groups_missing"] == ["chest", "shoulders"]

    even = wr.coverage(session("band_seated_row", "incline_pushup", "bird_dog"))
    assert even["upper_body_balance"]["note"] == "Pushing and pulling are roughly balanced (1 push, 1 pull)."
    assert (even["upper_body_balance"]["push"], even["upper_body_balance"]["pull"],
            even["upper_body_balance"]["static"]) == (1, 1, 1)                       # Bird Dog is a static back move

    lower = wr.coverage(session("bodyweight_squat", "glute_bridge", "dead_bug"))
    assert lower["upper_body_balance"]["note"] == "No upper-body exercises, so there's no push/pull balance to check."
    assert lower["notes"] == ["Back, chest, shoulders and arms weren't included."]

    core_missing = wr.coverage(session("bodyweight_squat", "band_seated_row", "incline_pushup", "burpee"))
    assert core_missing["notes"] == [
        "Chest, shoulders and core weren't included.",
        "1 full-body move also works several groups at once, but it isn't counted toward a single group here."]


# ================================================================ 2. the estimate, against hand-worked numbers

def test_estimate_matches_hand_calculation_for_weight_loss():
    # 165 lb = 74.84 kg; 30 min = 0.5 h.  3.5 x 74.84 x 0.5 = 130.97 -> 130 (down to 5)
    # 7.5 x 74.84 x 0.5 = 280.66 -> 285 (up to 5).  x 4 days = 520 to 1140 a week.
    # 8 weeks: 520 x 8 / 3500 = 1.19 -> 1.1 lb (down);  1140 x 8 / 3500 = 2.61 -> 2.7 lb (up)
    e = wr.estimate(30, 165, 4, ["weight_loss", "rehab"], "8_weeks")
    assert e["per_session_kcal"] == {"low": 130, "high": 285}
    assert e["weekly_kcal"] == {"low": 520, "high": 1140}
    assert e["weight_change"]["weeks"] == 8 and e["weight_change"]["pounds"] == {"low": 1.1, "high": 2.7}
    assert "not a precise prediction" in e["weight_change"]["label"]
    assert wr.CAVEAT_POUNDS in e["caveats"] and wr.CAVEAT_DIET in e["caveats"]
    assert "small piece of weight change compared with eating" in wr.CAVEAT_DIET
    assert e["sources"] == ["compendium-physical-activities", "cdc-losing-weight"]
    assert (e["method"]["low"]["met"], e["method"]["low"]["code"], e["method"]["high"]["met"],
            e["method"]["high"]["code"]) == (3.5, "02054", 7.5, "02020")


def test_estimate_without_a_weight_loss_goal_has_no_pounds():
    # 200 lb = 90.72 kg; 45 min = 0.75 h.  3.5 x 90.72 x 0.75 = 238.1 -> 235;  7.5 x 90.72 x 0.75 = 510.3 -> 515
    e = wr.estimate(45, 200, 3, ["strength"], None)
    assert e["per_session_kcal"] == {"low": 235, "high": 515} and e["weekly_kcal"] == {"low": 705, "high": 1545}
    assert e["weight_change"] is None and e["sources"] == ["compendium-physical-activities"]
    assert wr.CAVEAT_POUNDS not in e["caveats"]


def test_estimate_is_always_a_range_and_never_invents_a_weight():
    for minutes, lb in ((5, 100), (20, 130), (60, 250), (90, 180)):
        e = wr.estimate(minutes, lb, 5, ["weight_loss"], "no_deadline")
        k, p = e["per_session_kcal"], e["weight_change"]["pounds"]
        assert k["low"] < k["high"] and k["low"] % 5 == 0 and k["high"] % 5 == 0
        assert p["low"] < p["high"] and e["weight_change"]["weeks"] == 4         # no deadline: next 4 weeks
    assert wr.estimate(30, None, 4, ["weight_loss"], "8_weeks")["available"] is False


# ================================================================ 3. the model narrates; it can't invent a number

def test_model_cannot_invent_its_own_number(client, narrator):
    """The model tries, three times, to give its own figures (a single number, a rounded one, a converted one).
    Each is rejected; the reply the user gets is code-written, and contains only the code's numbers."""
    n = narrator("Nice work! You'll burn about 200 calories a session.",          # a number not in the data
                 "Roughly 131 to 281 calories a session.",                         # 'rounded' differently
                 "That's around 0.04 pounds a day.")                               # converted
    uid, h = account(client, "numbers@example.com")
    r = review_api(client, h)
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    allowed = numbers_in(review_for_model(res))
    assert numbers_in(res["summary"]) <= allowed                                   # THE guarantee
    assert res["summary_by"] == "code" and res["summary"] == plain_summary(res)
    assert n.calls == 3                                                            # first try + 2 retries
    assert not {"200", "131", "281", "0.04"} & numbers_in(res["summary"])


def test_model_narration_is_kept_when_it_only_uses_the_codes_numbers(client, narrator):
    uid, h = account(client, "goodnumbers@example.com")
    res = review_api(client, h).json()["result"]                                   # learn the computed numbers
    k = res["estimate"]["per_session_kcal"]
    good = (f"A solid mix of legs, arms and core. Next time a back or shoulder move would round it out. "
            f"A session like this burns roughly {k['low']} to {k['high']} calories, an estimate that depends on effort.")
    n = narrator(good)
    res = review_api(client, h).json()["result"]
    assert (res["summary"], res["summary_by"], n.calls) == (good, "model", 1)


@pytest.mark.parametrize("attempt", [
    "You will lose 2.7 pounds by your deadline!",                                  # allowed number, but a promise
    "Great job, no excuses, burn off that dessert!",                               # tone guard
])
def test_promises_and_shaming_are_rejected_even_with_allowed_numbers(client, narrator, attempt):
    narrator(attempt)
    uid, h = account(client, "tone@example.com")
    res = review_api(client, h).json()["result"]
    assert res["summary_by"] == "code" and res["summary"] != attempt


# ================================================================ 4. the routes

def test_review_route_returns_coverage_estimate_and_citations(client, narrator):
    narrator("A friendly summary without numbers.")
    uid, h = account(client, "route@example.com")
    r = review_api(client, h).json()
    res = r["result"]
    assert [e["name"] for e in res["exercises"]] == ["Dead Bug", "Incline Push-Up", "Bodyweight Squat"]
    assert res["coverage"]["groups_missing"] == ["back", "chest", "shoulders"]
    assert res["estimate"]["available"] and res["estimate"]["weight_change"]["weeks"] == 8
    assert {c["id"] for c in res["citations"]} == {"compendium-physical-activities", "cdc-losing-weight"}
    assert all(c["url"].startswith("https://") for c in res["citations"])
    assert rows("SELECT agent_name, route, user_id, status FROM agent_runs") == [
        {"agent_name": "workout_reviewer", "route": "POST /api/workouts/review", "user_id": uid, "status": "ok"}]
    assert any(s["id"] == "compendium-physical-activities" for s in client.get("/api/sources").json())


def test_review_route_rejects_bad_input(client, narrator):
    n = narrator("x")
    uid, h = account(client, "badinput@example.com")
    assert review_api(client, h, [{"exercise_id": "made_up", "sets": 2, "reps": "8", "rest_seconds": 30}]).status_code == 422
    assert review_api(client, h, []).status_code == 422
    assert client.post("/api/workouts/review", headers=h, json={"items": ITEMS, "user_id": 1}).status_code == 422
    assert client.post("/api/workouts/review", json={"items": ITEMS}).status_code == 401
    assert n.calls == 0


def test_calendar_review_is_for_custom_days_only(client, on_day, use_script, narrator):
    uid, h = account(client, "calreview@example.com")
    other, oh = account(client, "calother@example.com")
    days = by_date(get_days(client, h))
    use_script(*CORE_SCRIPT)                                                       # the Workout Builder
    assert client.post(f"/api/calendar/{days[d(2)]['id']}/custom", headers=h,
                       json={"picks": {"core": 2}, "time_budget_minutes": 15}).status_code == 200
    n = narrator("A short, kind summary.")                                         # the Workout Reviewer
    r = client.post(f"/api/calendar/{days[d(2)]['id']}/review", headers=h)
    assert r.status_code == 200, r.text
    assert [e["name"] for e in r.json()["result"]["exercises"]] == ["Dead Bug", "Pelvic Tilt"]
    assert client.post(f"/api/calendar/{days[d(4)]['id']}/review", headers=h).status_code == 409   # generated day
    assert client.post(f"/api/calendar/{days[d(2)]['id']}/review", headers=oh).status_code == 404  # not theirs
    assert n.calls == 1


# ================================================================ 5. safety: pregnancy block and PII

@pytest.mark.parametrize("status", ["pregnant", "postpartum"])
def test_pregnant_and_postpartum_users_are_blocked_at_the_api(client, on_day, use_script, narrator, status):
    uid, h = account(client, f"review-{status}@example.com")
    days = by_date(get_days(client, h))
    use_script(*CORE_SCRIPT)
    client.post(f"/api/calendar/{days[d(2)]['id']}/custom", headers=h, json={"picks": {"core": 2}, "time_budget_minutes": 15})
    n = narrator("should never be used")
    runs_before = rows("SELECT COUNT(*) AS n FROM agent_runs")[0]["n"]

    retake(client, uid, h, pregnancy_status=status)
    for r in (review_api(client, h), client.post(f"/api/calendar/{days[d(2)]['id']}/review", headers=h)):
        assert r.status_code == 403, r.text
        assert r.json()["detail"]["code"] == "needs_clinical_review" and r.json()["detail"]["page"] == "/pregnancy-support"
    assert n.calls == 0 and rows("SELECT COUNT(*) AS n FROM agent_runs")[0]["n"] == runs_before


def test_the_model_never_sees_who_the_user_is(client, narrator):
    n = narrator("A kind summary.")
    email = "very.private.person@example.com"
    r = client.post("/api/users", json={"email": email, "password": "correct horse 1"}).json()
    h = {"Authorization": f"Bearer {r['token']}"}
    from tests.helpers import quiz_answers
    client.put(f"/api/users/{r['user_id']}/quiz-profile", headers=h, json={
        "consent_accepted": True, "consent_version": "t", "injury_notes": "PRIVATE-INJURY-NOTE from Dr. Smith",
        "answers": quiz_answers(weight=173, other_activity_notes="PRIVATE-ACTIVITY-NOTE")})
    review_api(client, h)
    sent = " ".join(n.seen)
    for secret in (email, "very.private", "PRIVATE-INJURY-NOTE", "Dr. Smith", "PRIVATE-ACTIVITY-NOTE",
                   '"user_id"', '"weight_lb"', '"weight":', "173"):
        assert secret not in sent, secret
    assert "per_session_kcal" in sent                                              # it did get the computed review

"""Workout Builder agent: "pick your own workout" from the user's picks and time budget.

Triggered by POST /api/workouts/build. Model-visible tools: get_user_profile, search_exercises.

Enforced in code (backend/prompts/shared_rules.md):
- user_id comes from the session (rule 2). The user's equipment comes from the request, and
  injury_flags + checked_only from the profile; all three are added to every exercise search, so the
  model can't widen it (rule 4). checked_only is true whenever the user has an injury flag.
- Every exercise in the plan must be one the tool returned this run (no invented exercises), with
  the requested number per muscle group (fewer only if the filtered library has fewer).
- Total time is computed by code, and the plan must fit the time budget.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.harness import AgentDeps, McpGateway, harness_flags, load_prompt, no_emoji, run_logged

MuscleGroup = Literal["legs", "arms", "chest", "shoulders", "back", "core", "full_body"]
MAX_PER_GROUP, MAX_TOTAL = 6, 12


class WorkoutRequest(BaseModel):
    """Request body. Deliberately has no user_id (that comes from the sign-in) and forbids extra fields."""
    model_config = {"extra": "forbid"}
    picks: dict[MuscleGroup, int] = Field(description='e.g. {"legs": 3, "arms": 3}')
    time_budget_minutes: int = Field(ge=5, le=120)
    equipment: list[str] | None = Field(None, description="equipment the user has; omit for any")

    @field_validator("picks")
    @classmethod
    def _sane(cls, picks: dict[str, int]) -> dict[str, int]:
        if not picks or any(n < 1 or n > MAX_PER_GROUP for n in picks.values()) or sum(picks.values()) > MAX_TOTAL:
            raise ValueError(f"pick 1-{MAX_PER_GROUP} exercises per muscle group, at most {MAX_TOTAL} in total")
        return picks


class PlannedItem(BaseModel):
    exercise_id: str
    sets: int = Field(ge=1, le=6)
    reps: str = Field(description='e.g. "10", "8 each side", "30s"', max_length=30)
    rest_seconds: int = Field(ge=15, le=180)


class WorkoutDraft(BaseModel):
    items: list[PlannedItem] = Field(description="exercises in the order to do them")
    balance_note: str = Field(description="one line on balance (push/pull, front/back, upper/lower); "
                                          "say plainly if it's unbalanced", max_length=200)


class SessionExercise(BaseModel):
    order: int
    exercise_id: str
    name: str
    muscle_group: str
    sets: int
    reps: str
    rest_seconds: int
    est_minutes: float
    injury_check: str


class WorkoutSession(BaseModel):
    exercises: list[SessionExercise]
    total_estimated_minutes: float
    time_budget_minutes: int
    balance_note: str
    notes: list[str] = []


workout_builder = Agent(
    name="workout_builder",
    deps_type=AgentDeps,
    output_type=WorkoutDraft,
    instructions=load_prompt("workout_builder"),
    retries=3,
)


@workout_builder.instructions
def _request(ctx: RunContext[AgentDeps]) -> str:
    r = ctx.deps.seen["request"]
    picks = ", ".join(f"{n} {g}" for g, n in r.picks.items())
    return f"## This request\nPicks: {picks}. Time budget: {r.time_budget_minutes} minutes."


@workout_builder.tool
async def get_user_profile(ctx: RunContext[AgentDeps]) -> dict:
    """The signed-in user's goal and injury flags."""
    return await ctx.deps.gateway.call("get_user_profile", {"user_id": ctx.deps.user_id})


@workout_builder.tool
async def search_exercises(ctx: RunContext[AgentDeps], muscle_group: MuscleGroup, limit: int = 15) -> dict:
    """Exercises for one muscle group. The user's equipment and injury filters are applied automatically."""
    req = ctx.deps.seen["request"]
    result = await ctx.deps.gateway.call("search_exercises", {
        "muscle_group": muscle_group, "equipment": req.equipment, "limit": max(1, min(limit, 30)),
        "injury_flags": ctx.deps.injury_flags, "checked_only": ctx.deps.checked_only})
    ctx.deps.seen.setdefault("exercises", {}).update({e["id"]: e for e in result["exercises"]})
    ctx.deps.seen.setdefault("available", {})[muscle_group] = result["total_matching"]
    # The model gets a slim list (fewer tokens); the full records stay with the code for the checks.
    return {
        "muscle_group": muscle_group,
        "total_matching": result["total_matching"],
        "exercises": [{k: e[k] for k in ("id", "name", "equipment_needed", "difficulty", "est_time_seconds",
                                         "injury_check")} for e in result["exercises"]],
    }


def item_seconds(item: PlannedItem, est_time_seconds: int) -> int:
    """sets x the exercise's time per set (which includes setup) + rest between sets."""
    return item.sets * est_time_seconds + (item.sets - 1) * item.rest_seconds


@workout_builder.output_validator
async def _check(ctx: RunContext[AgentDeps], draft: WorkoutDraft) -> WorkoutDraft:
    req, seen = ctx.deps.seen["request"], ctx.deps.seen.get("exercises", {})
    available = ctx.deps.seen.get("available", {})
    ids = [i.exercise_id for i in draft.items]
    unknown = [i for i in ids if i not in seen]
    if unknown:
        raise ModelRetry(f"These ids weren't returned by search_exercises: {unknown}. Use only returned ids.")
    if len(set(ids)) != len(ids):
        raise ModelRetry("Each exercise may appear only once.")
    counts: dict[str, int] = {}
    for i in ids:
        counts[seen[i]["muscle_group"]] = counts.get(seen[i]["muscle_group"], 0) + 1
    for group, wanted in req.picks.items():
        if group not in available:
            raise ModelRetry(f"Search the '{group}' group first.")
        need = min(wanted, available[group])
        if counts.get(group, 0) != need:
            raise ModelRetry(f"Include exactly {need} '{group}' exercise(s); you have {counts.get(group, 0)}.")
    extra = set(counts) - set(req.picks)
    if extra:
        raise ModelRetry(f"Only use the picked muscle groups; remove {sorted(extra)}.")
    total = sum(item_seconds(i, seen[i.exercise_id]["est_time_seconds"]) for i in draft.items) / 60
    if total > req.time_budget_minutes:
        raise ModelRetry(f"That takes about {total:.0f} minutes, over the {req.time_budget_minutes}-minute "
                         "budget. Use fewer sets or shorter rests (keep the exercise counts).")
    return draft


def finalize(draft: WorkoutDraft, deps: AgentDeps) -> WorkoutSession:
    req, seen = deps.seen["request"], deps.seen["exercises"]
    exercises = []
    for n, item in enumerate(draft.items, 1):
        e = seen[item.exercise_id]
        exercises.append(SessionExercise(
            order=n, exercise_id=e["id"], name=e["name"], muscle_group=e["muscle_group"], sets=item.sets,
            reps=item.reps, rest_seconds=item.rest_seconds, injury_check=e["injury_check"],
            est_minutes=round(item_seconds(item, e["est_time_seconds"]) / 60, 1)))
    notes = []
    for group, wanted in req.picks.items():
        got = sum(1 for x in exercises if x.muscle_group == group)
        if got < wanted:
            notes.append(f"Only {got} {group} exercise(s) are available with your equipment"
                         + (" and injury filters" if deps.injury_flags else "") + f" (you asked for {wanted}).")
    unchecked = [x.name for x in exercises if x.injury_check == "not_yet_checked"]
    if unchecked:
        notes.append(f"Not yet checked for injury safety: {', '.join(unchecked)}. Skip anything that hurts.")
    if deps.injury_flags:
        notes.append("Exercises flagged as unsafe for your injuries, or not yet checked for injury safety, "
                     "were left out automatically.")
    return WorkoutSession(exercises=exercises, time_budget_minutes=req.time_budget_minutes,
                          total_estimated_minutes=round(sum(x.est_minutes for x in exercises), 1),
                          balance_note=no_emoji(draft.balance_note), notes=notes)


async def build_workout(user_id: int, request: WorkoutRequest, route: str) -> tuple[WorkoutSession, dict]:
    deps = AgentDeps(gateway=McpGateway(), user_id=user_id)
    deps.profile = await deps.gateway.call("get_user_profile", {"user_id": user_id}, called_by="code")
    deps.injury_flags, deps.checked_only = harness_flags(deps.profile)
    deps.seen["request"] = request
    draft, meta = await run_logged(workout_builder, agent_name="workout_builder", deps=deps, route=route,
                                   prompt="Build my workout.")
    return finalize(draft, deps), meta

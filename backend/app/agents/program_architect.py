"""Program Architect agent: recommends one trainer program template for the signed-in user.

Triggered by POST /api/programs/recommend. Model-visible tools: get_user_profile, search_program_templates.

Enforced in code, not left to the model (backend/prompts/shared_rules.md):
- user_id comes from the session; the model's tools have no user_id parameter (rule 2).
- injury_flags and checked_only are added to every program search from the profile;
  checked_only is true whenever the user has an injury flag (rule 4). The model can't change them.
- The recommended program must be one the tool returned this run; its name, status, citations and
  review notice are copied from the tool result, so the model can't invent or upgrade them (rule 1).
- If the program has no citations, a rationale that claims scientific backing is replaced (rule 1).
- If nothing fits the user's goals, the answer says so instead of overselling a weak match.
"""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.harness import AgentDeps, McpGateway, harness_flags, load_prompt, makes_science_claim, run_logged

GoalTag = Literal["weight_loss", "tone", "strength", "rehab"]
PENDING_NOTE = ("Pending expert review: this program hasn't been checked by a physical therapist yet, "
                "so treat it as a starting point, not verified advice.")


class ProgramDraft(BaseModel):
    """What the model returns. Everything factual is filled in afterwards from the tool results."""
    recommended: bool = Field(description="false if no returned program fits the user's goals well")
    program_id: int | None = Field(None, description="id of the chosen program, exactly as returned by the tool")
    rationale: str = Field(description="2-3 friendly sentences on why it fits, using only the program's own text",
                           max_length=800)
    no_match_reason: str | None = Field(None, description="if recommended is false: why, in one sentence",
                                        max_length=300)


class ProgramRecommendation(BaseModel):
    recommended: bool
    program_id: int | None = None
    name: str | None = None
    rationale: str
    goal_tags: list[str] = []
    matched_goals: list[str] = []
    status: str | None = None
    review_notice: str | None = None
    review_note: str | None = None          # plain-language "pending expert review" note
    citations: list[dict] = []
    injury_note: str | None = None
    schedule: dict | None = None
    message: str | None = None              # set when nothing is recommended


program_architect = Agent(
    name="program_architect",
    deps_type=AgentDeps,
    output_type=ProgramDraft,
    instructions=load_prompt("program_architect"),
    retries=2,
)


@program_architect.tool
async def get_user_profile(ctx: RunContext[AgentDeps]) -> dict:
    """The signed-in user's goals, timeline, injury flags, age, weight and height."""
    return await ctx.deps.gateway.call("get_user_profile", {"user_id": ctx.deps.user_id})


@program_architect.tool
async def search_program_templates(ctx: RunContext[AgentDeps], goal_tags: list[GoalTag] | None = None) -> dict:
    """Search the trainer program templates by goal. Injury filtering is applied automatically for this user."""
    result = await ctx.deps.gateway.call("search_program_templates", {
        "goal_tags": goal_tags, "injury_flags": ctx.deps.injury_flags, "checked_only": ctx.deps.checked_only})
    ctx.deps.seen.setdefault("programs", {}).update({p["id"]: p for p in result["programs"]})
    return result


@program_architect.output_validator
async def _check(ctx: RunContext[AgentDeps], draft: ProgramDraft) -> ProgramDraft:
    seen = ctx.deps.seen.get("programs", {})
    if draft.recommended and draft.program_id not in seen and ctx.retry >= ctx.max_retries:
        return draft.model_copy(update={"recommended": False, "program_id": None,
                                        "no_match_reason": "We couldn't settle on a program from our library."})
    if draft.recommended:
        if not seen:
            raise ModelRetry("Call search_program_templates before recommending a program.")
        if draft.program_id not in seen:
            raise ModelRetry(f"program_id must be one of the programs the tool returned: {sorted(seen)}.")
    return draft


def _no_match(message: str) -> ProgramRecommendation:
    return ProgramRecommendation(recommended=False, rationale=message, message=message)


def finalize(draft: ProgramDraft, deps: AgentDeps) -> ProgramRecommendation:
    """Turn the model's choice into the response, with every fact taken from the tool results."""
    goals = set((deps.profile or {}).get("goals") or [])
    if not draft.recommended or draft.program_id is None:
        return _no_match(draft.no_match_reason or "None of our programs is a good fit for your goals right now.")
    p = deps.seen["programs"][draft.program_id]
    matched = sorted(goals & set(p["goal_tags"]))
    if goals and not matched:   # a program for different goals isn't a match, however it's described
        return _no_match(f"Our closest program, {p['name']}, is built for {', '.join(p['goal_tags'])}, not your "
                         "goals, so we'd rather not push it on you. Try building your own workout instead.")
    rationale = draft.rationale.strip()
    if not p["citations"] and makes_science_claim(rationale):
        rationale = (f"{p['name']} matches your goals ({', '.join(matched) or 'general fitness'}). "
                     f"{p['description']} Its rationale is still pending expert review, so we can't point to "
                     "verified evidence for it yet.")
    return ProgramRecommendation(
        recommended=True, program_id=p["id"], name=p["name"], rationale=rationale, goal_tags=p["goal_tags"],
        matched_goals=matched, status=p["status"], review_notice=p["review_notice"],
        review_note=PENDING_NOTE if p["status"] == "placeholder" else None, citations=p["citations"],
        injury_note=p["injury_note"], schedule=p["schedule"])


async def recommend_program(user_id: int, route: str) -> tuple[ProgramRecommendation, dict]:
    deps = AgentDeps(gateway=McpGateway(), user_id=user_id)
    deps.profile = await deps.gateway.call("get_user_profile", {"user_id": user_id}, called_by="code")
    if not deps.profile.get("found"):
        return _no_match("Take the quiz first so we know your goals."), {"tool_calls": deps.gateway.calls}
    deps.injury_flags, deps.checked_only = harness_flags(deps.profile)

    # If nothing can possibly match, say so without spending tokens on the model.
    pre = await deps.gateway.call("search_program_templates", {
        "goal_tags": deps.profile["goals"], "injury_flags": deps.injury_flags, "checked_only": deps.checked_only},
        called_by="code")
    if pre["count"] == 0:
        excluded = pre["injury_filter"]["excluded_programs"]
        why = (" Some programs were left out because they include exercises that aren't cleared for your "
               "injuries yet." if excluded else "")
        return _no_match("None of our programs matches your goals right now." + why), {"tool_calls": deps.gateway.calls}

    draft, meta = await run_logged(program_architect, agent_name="program_architect", deps=deps, route=route,
                                   prompt="Recommend the best program for me.")
    return finalize(draft, deps), meta

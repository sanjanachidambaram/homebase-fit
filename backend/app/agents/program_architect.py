"""Program Architect agent: EXPLAINS the user's generated weekly plan. It no longer searches or picks anything.

Triggered by POST /api/programs/recommend.
  1. Code builds the plan: app/services/program_generator.py (deterministic, no LLM, injury filter applied).
  2. This agent gets the finished plan, the user's goals, and the protocol's status and citations, and writes
     a short, warm, honest explanation of why the plan fits. It has NO tools: everything it may use is in
     the prompt, so it can't fetch anything else.

Enforced in code (shared_rules.md, rules 1 and 2):
- The model sees no user id and no profile fields beyond goals and experience level.
- If the protocol has no citations, an explanation that claims scientific backing is sent back for a rewrite,
  then replaced with a plain one if it still does.
- The "pending expert review" note comes from code, not from the model.
- No plan (pregnant/postpartum): the code explains, and the model is never called.
"""

import json

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.harness import AgentDeps, McpGateway, load_prompt, makes_science_claim, no_emoji, run_logged
from app.services.program_generator import WeeklyProgram, generate_for_user

PENDING_NOTE = ("Pending expert review: the training settings behind this plan haven't been checked by a "
                "physical therapist yet, so treat it as a starting point, not verified advice.")


class PlanExplanation(BaseModel):
    explanation: str = Field(description="3-4 warm, plain sentences on why this plan fits", max_length=900)


class PlanRecommendation(BaseModel):
    plan: WeeklyProgram
    explanation: str
    review_note: str | None = None


program_architect = Agent(
    name="program_architect",
    deps_type=AgentDeps,
    output_type=PlanExplanation,
    instructions=load_prompt("program_architect"),
    retries=2,
)


def plain_explanation(plan: WeeklyProgram) -> str:
    p = plan.protocol
    goals = " and ".join(g.replace("_", " ") for g in plan.goals)
    return (f"This plan is built around your {goals} goals: {plan.training_days} {p.split_type.replace('_', ' ')} "
            f"sessions a week of about {p.session_length_minutes} minutes, with rest days in between. "
            "Its training settings are still pending expert review, so we can't point to verified evidence yet.")


@program_architect.output_validator
async def _check(ctx: RunContext[AgentDeps], out: PlanExplanation) -> PlanExplanation:
    plan: WeeklyProgram = ctx.deps.seen["plan"]
    if not plan.protocol.citations and makes_science_claim(out.explanation):
        if ctx.retry >= ctx.max_retries:
            return PlanExplanation(explanation=plain_explanation(plan))
        raise ModelRetry("This plan's protocol has no citations, so don't say anything is proven, research-backed, "
                         "or scientific. Explain it plainly.")
    return out


def plan_for_model(plan: WeeklyProgram) -> str:
    """Everything the model may use, and nothing else: goals, the plan's structure, status and citations."""
    p = plan.protocol
    return json.dumps({
        "goals": plan.goals,
        "experience_level": plan.experience_level,
        "plan": {
            "training_days_per_week": plan.training_days,
            "split": p.split_type,
            "session_minutes": p.session_length_minutes,
            "sets": p.sets_range, "reps": p.reps_range, "rest_seconds": p.rest_seconds,
            "week": [{"day": d.day, "focus": d.focus, "exercises": [e.name for e in d.exercises]}
                     if d.kind == "training" else {"day": d.day, "rest": True} for d in plan.days],
            "low_impact_injury_safe": plan.safety.checked_only,
        },
        "protocol_status": p.status,
        "citations": p.citations,
    }, separators=(",", ":"))


async def recommend_plan(user_id: int, route: str) -> tuple[PlanRecommendation, dict]:
    plan = generate_for_user(user_id)            # code, not the model (raises NoProfile without a quiz)
    if not plan.generated:                       # e.g. pregnant/postpartum: explained by code, no model call
        return PlanRecommendation(plan=plan, explanation=plan.blocked_reason), {"agent_called": False}
    deps = AgentDeps(gateway=McpGateway(), user_id=user_id)
    deps.seen["plan"] = plan
    out, meta = await run_logged(program_architect, agent_name="program_architect", deps=deps, route=route,
                                 prompt=plan_for_model(plan))
    explanation = no_emoji(out.explanation)
    if not plan.protocol.citations and makes_science_claim(explanation):   # never ship an unsupported claim
        explanation = plain_explanation(plan)
    return PlanRecommendation(plan=plan, explanation=explanation,
                              review_note=PENDING_NOTE if plan.protocol.status == "placeholder" else None), meta

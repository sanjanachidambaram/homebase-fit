"""Coach / motivation agent: a short, warm message for the dashboard.

Triggered by GET /api/coach/summary. Model-visible tools: get_progress_summary, check_goal_achievement,
compute_strength_equivalents.

Enforced in code:
- user_id comes from the session; the two user tools take no arguments from the model (rule 2).
- goal_status and overtraining_flag come straight from the tool data, never from the model's text:
  overtraining_flag is true at 10+ consecutive logged days (get_progress_summary.current_streak_days).
- The fun fact is built by code from compute_strength_equivalents (the model only picks which
  comparison), so the numbers can't be made up.
- Tone guard: no body-shaming, guilt, or food/weight talk. A message that trips the guard is sent
  back to the model to rewrite, and replaced with a plain encouraging line if it still fails.
"""

import re

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.harness import AgentDeps, McpGateway, load_prompt, run_logged
from app.mcp_server.progress import REST_SUGGESTED_AFTER_DAYS

TONE_BLOCKLIST = re.compile(
    r"\b(calorie\w*|burn (it )?off|cheat (meal|day)\w*|guilt\w*|lazy|fat|skinny|slim(mer)?|bikini|beach body|"
    r"diet\w*|food|eat\w*|snack\w*|dessert|pizza|treat yourself|earn(ed)? (it|your)|no excuses|excuses?|"
    r"body ?weight|weigh(ed|ing|-in)?|scale|pounds lost|lose weight|lost weight|flab\w*|jiggl\w*|shame\w*|"
    r"disappoint\w*|should have|slacking|slacker)\b", re.I)
SAFE_ENCOURAGEMENT = "Every bit of movement counts, and you're building a habit that's all yours. Keep showing up for you!"


class CoachDraft(BaseModel):
    encouragement: str = Field(description="2-3 warm, upbeat sentences", max_length=450)
    fun_fact_comparison: str | None = Field(
        None, description="the `name` of one comparison from compute_strength_equivalents to feature, or null")


class CoachMessage(BaseModel):
    encouragement: str
    fun_fact: str | None
    goal_status: str            # on_track | ahead | behind | insufficient_data (from check_goal_achievement)
    overtraining_flag: bool     # 10+ consecutive logged days, from get_progress_summary
    rest_suggestion: str | None
    current_streak_days: int
    sessions_last_30_days: int
    total_weight_lifted_lbs: float


coach = Agent(
    name="coach",
    deps_type=AgentDeps,
    output_type=CoachDraft,
    instructions=load_prompt("coach"),
    retries=2,
)


@coach.tool
async def get_progress_summary(ctx: RunContext[AgentDeps]) -> dict:
    """The signed-in user's last 30 days: sessions, weight lifted, streak, measurement trends."""
    result = await ctx.deps.gateway.call("get_progress_summary", {"user_id": ctx.deps.user_id})
    ctx.deps.seen["summary"] = result
    return result


@coach.tool
async def check_goal_achievement(ctx: RunContext[AgentDeps]) -> dict:
    """Whether the signed-in user is on track for their quiz goals (simple app thresholds, not science)."""
    result = await ctx.deps.gateway.call("check_goal_achievement", {"user_id": ctx.deps.user_id})
    ctx.deps.seen["goal"] = result
    return result


@coach.tool
async def compute_strength_equivalents(ctx: RunContext[AgentDeps], total_weight_lifted_lbs: float) -> dict:
    """Fun comparisons (pianos, cars, elephants...) for a total weight lifted, in pounds."""
    result = await ctx.deps.gateway.call("compute_strength_equivalents",
                                         {"total_weight_lifted_lbs": total_weight_lifted_lbs})
    ctx.deps.seen["equivalents"] = result
    return result


def tone_problems(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in TONE_BLOCKLIST.finditer(text or "")})


@coach.output_validator
async def _check(ctx: RunContext[AgentDeps], draft: CoachDraft) -> CoachDraft:
    bad = tone_problems(draft.encouragement)
    if bad and ctx.retry >= ctx.max_retries:   # out of retries: ship the plain safe line instead of failing
        return draft.model_copy(update={"encouragement": SAFE_ENCOURAGEMENT})
    if bad:
        raise ModelRetry(f"Rewrite without these words: {bad}. Celebrate effort and consistency only; "
                         "never mention food, eating, body size, or body weight.")
    return draft


async def finalize(draft: CoachDraft, deps: AgentDeps) -> CoachMessage:
    gw = deps.gateway
    # The facts come from the tools. If the model skipped a tool, the code calls it itself.
    summary = deps.seen.get("summary") or await gw.call("get_progress_summary", {"user_id": deps.user_id},
                                                        called_by="code")
    goal = deps.seen.get("goal") or await gw.call("check_goal_achievement", {"user_id": deps.user_id},
                                                  called_by="code")
    lifted = float(summary.get("total_weight_lifted_lbs") or 0)
    eq = deps.seen.get("equivalents")
    if not eq or eq.get("total_weight_lifted_lbs") != round(lifted, 1):
        eq = await gw.call("compute_strength_equivalents", {"total_weight_lifted_lbs": lifted}, called_by="code")
    comparisons = {c["name"]: c for c in eq.get("comparisons", [])}
    if not comparisons:
        fun_fact = None
    elif draft.fun_fact_comparison in comparisons:
        fun_fact = f"In the last 30 days you've lifted {comparisons[draft.fun_fact_comparison]['phrase']}!"
    else:
        fun_fact = eq["headline"]

    streak = int(summary.get("current_streak_days") or 0)
    overtraining = streak >= REST_SUGGESTED_AFTER_DAYS
    encouragement = draft.encouragement.strip()
    if tone_problems(encouragement):   # belt and braces: never ship a message that fails the tone guard
        encouragement = SAFE_ENCOURAGEMENT
    return CoachMessage(
        encouragement=encouragement, fun_fact=fun_fact, goal_status=goal.get("status", "insufficient_data"),
        overtraining_flag=overtraining,
        rest_suggestion=(f"You've trained {streak} days in a row. Your muscles get stronger while you rest, so "
                         "take a rest day (or an easy walk) before your next session." if overtraining else None),
        current_streak_days=streak, sessions_last_30_days=int(summary.get("sessions_logged") or 0),
        total_weight_lifted_lbs=lifted)


async def coach_summary(user_id: int, route: str) -> tuple[CoachMessage, dict]:
    deps = AgentDeps(gateway=McpGateway(), user_id=user_id)
    draft, meta = await run_logged(coach, agent_name="coach", deps=deps, route=route,
                                   prompt="Write my dashboard message.")
    return await finalize(draft, deps), meta

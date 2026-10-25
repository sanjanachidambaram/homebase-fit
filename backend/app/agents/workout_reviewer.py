"""Workout Reviewer agent: NARRATES a review that code already computed. It never computes anything.

Triggered by POST /api/workouts/review (a Build Your Own session) and POST /api/calendar/{id}/review (a custom
calendar day), both in app/agent_routes.py.
  1. Code computes the review: app/services/workout_review.py (coverage, push/pull balance, and the
     Compendium-based calorie / weight-change range, with its caveats and citations).
  2. This agent gets that result (and nothing about the person: no id, username, name, email, weight or free text) and
     writes a short, warm explanation. It has NO tools.

Enforced in code (shared_rules.md rule 7):
- Every number in the model's text must appear in the data it was given. A draft with any other number is sent
  back once or twice, then replaced by a plain explanation written by code. So the narration can never show a
  number the code didn't compute.
- The same for coverage claims: code decides which of the 4 workout groups (Cardio, Upper body, Lower body,
  Mobility + core) the session includes. A draft that says the session lacks a group it actually includes is sent
  back the same way.
- A tone guard like the Coach's (no shaming, guilt, food-guilt or body talk), plus no promises ("you will lose
  ..."). Unlike the Coach's list it allows "calories" and "pounds": explaining that estimate is this agent's job.
"""

import json
import re

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.harness import AgentDeps, McpGateway, load_prompt, no_emoji, run_logged

NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# The Coach's blocklist minus the words this agent needs for its estimate (calories, pounds, weight, eating habits).
TONE = re.compile(
    r"\b(burn (it |that )?off|cheat (meal|day)\w*|guilt\w*|lazy|fat|skinny|slim(mer)?|bikini|beach body|"
    r"dessert|pizza|treat yourself|earn(ed)? (it|your)|no excuses|excuses?|flab\w*|jiggl\w*|shame\w*|"
    r"disappoint\w*|should have|slacking|slacker)\b", re.I)
# A sentence that says something is absent ("doesn't include any cardio", "no core work", "missing ...").
ABSENCE = re.compile(r"\b(no|not|without|missing|lacks?|lacking|skips?|skipped)\b|n't\b", re.I)
GROUP_MENTION = {"cardio": re.compile(r"\bcardio", re.I),
                 "upper": re.compile(r"\bupper[- ]body", re.I),
                 "lower": re.compile(r"\blower[- ]body|\blegs?\b", re.I),
                 "mobility_core": re.compile(r"\bmobility|\bcore\b|\bstretch", re.I)}
PROMISE = re.compile(r"\b(guarantee\w*|you will (lose|burn|drop|shed)|you'll (lose|burn|drop|shed)|definitely|"
                     r"for sure|certainly will)\b", re.I)


class ReviewNarration(BaseModel):
    summary: str = Field(description="3-5 warm, plain sentences about the review", max_length=1000)


workout_reviewer = Agent(
    name="workout_reviewer",
    deps_type=AgentDeps,
    output_type=ReviewNarration,
    instructions=load_prompt("workout_reviewer"),
    retries=2,
)


def _canon(token: str) -> str:
    """'3,500' -> '3500', '02054' -> '2054', '3.50' -> '3.5', so the same number always compares equal."""
    try:
        return f"{float(token.replace(',', '')):g}"
    except ValueError:
        return token


def numbers_in(text: str) -> set[str]:
    return {_canon(t) for t in NUMBER.findall(text or "")}


def review_for_model(review: dict) -> str:
    """Exactly what the model sees: the computed review. No user id, profile fields, weight or free text."""
    return json.dumps({k: review[k] for k in ("exercises", "coverage", "estimate", "citations")},
                      separators=(",", ":"))


def false_absences(summary: str, coverage: dict) -> list[str]:
    """Workout groups the narration says are missing although code found them in the session."""
    present = {g["group"] for g in coverage["groups_hit"]}
    # In each sentence, what comes after the first absence word: "it has upper-body work but no cardio" -> "no cardio"
    tails = [x[m.start():] for x in re.split(r"(?<=[.!?])\s+", summary or "") if (m := ABSENCE.search(x))]
    return sorted(g for g in present if any(GROUP_MENTION[g].search(t) for t in tails))


def plain_summary(review: dict) -> str:
    """The code-written fallback: only facts and numbers straight from the review."""
    cov, est = review["coverage"], review["estimate"]
    hit = [g["label"].lower() for g in cov["groups_hit"]]
    parts = [f"This session includes {', '.join(hit[:-1]) + ' and ' + hit[-1] if len(hit) > 1 else hit[0]} work."
             if hit else "", cov["suggestion"] or "It covers all four workout groups.",
             cov["upper_body_balance"]["note"]]
    parts = [x for x in parts if x] + cov["notes"]
    if est.get("available"):
        k = est["per_session_kcal"]
        parts.append(f"A session like this burns roughly {k['low']} to {k['high']} calories, depending on how hard "
                     "you work.")
    return " ".join(parts)


@workout_reviewer.output_validator
async def _check(ctx: RunContext[AgentDeps], out: ReviewNarration) -> ReviewNarration:
    review = ctx.deps.seen["review"]
    invented = sorted(numbers_in(out.summary) - numbers_in(review_for_model(review)))
    problems = []
    if invented:
        problems.append(f"Only use numbers that appear in the data. These don't: {invented}. Restate the given "
                        "ranges exactly, or leave numbers out.")
    wrong = false_absences(out.summary, review["coverage"])
    if wrong:
        problems.append(f"The session DOES include {', '.join(wrong)} work (see coverage.groups_hit). Only call a "
                        "group missing if it's in coverage.groups_missing.")
    if TONE.search(out.summary):
        problems.append("Keep it kind and body-neutral: no shaming, guilt, or talk about how bodies look.")
    if PROMISE.search(out.summary):
        problems.append("Don't promise results. These are rough estimates, so say 'roughly' or 'might'.")
    if problems:
        if ctx.retry >= ctx.max_retries:
            ctx.deps.seen["fallback"] = True
            return ReviewNarration(summary=plain_summary(review))
        raise ModelRetry(" ".join(problems))
    return out


async def narrate(user_id: int, review: dict, route: str) -> tuple[dict, dict]:
    deps = AgentDeps(gateway=McpGateway(), user_id=user_id)
    deps.seen["review"] = review
    out, meta = await run_logged(workout_reviewer, agent_name="workout_reviewer", deps=deps, route=route,
                                 prompt=review_for_model(review))
    summary = no_emoji(out.summary)
    # Belt and braces: whatever happened above, never ship a number the code didn't compute.
    if (numbers_in(summary) - numbers_in(review_for_model(review)) or PROMISE.search(summary) or TONE.search(summary)
            or false_absences(summary, review["coverage"])):
        summary, deps.seen["fallback"] = plain_summary(review), True
    return ({**review, "summary": summary, "summary_by": "code" if deps.seen.get("fallback") else "model"},
            {**meta, "agent_called": True})

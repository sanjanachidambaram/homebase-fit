"""Fitness Basics agent: answers questions from the Basics hub, ONLY from the knowledge base.

Triggered by POST /api/basics/ask. Model-visible tool: search_basics_kb (nothing else).

The pipeline, in order (each step can end the request before any model call):
  1. Red-flag pre-filter (app/agents/safety.py, plain code). A pain/injury warning sign means the agent
     is NEVER called: we log a safety_events row and return a fixed "see a professional" message.
  2. Knowledge-base check (code calls search_basics_kb). Nothing relevant means a fixed
     "I don't have verified information" reply, again with no model call (shared_rules rule 1.4).
  3. The agent answers from search_basics_kb results. Its sources must be articles the tool returned
     this run; their status, review notice and citations are copied in by code, never written by the model.
     If the sources have no citations, the answer may not claim scientific backing (rule 1).
"""

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext

from app.agents.harness import AgentDeps, McpGateway, load_prompt, makes_science_claim, run_logged
from app.agents.safety import REDIRECT_MESSAGE, log_safety_event, red_flags_in
from app.safety_rules import CLINICAL_REVIEW_NO_AI, CLINICAL_REVIEW_PAGE

NO_INFO_MESSAGE = "I don't have verified information on that. Please consult a doctor or physical therapist."
PENDING_NOTE = "This comes from our Fitness Basics guide, which is still pending expert review."


class BasicsQuestion(BaseModel):
    model_config = {"extra": "forbid"}   # no user_id or anything else can ride along in the body
    question: str = Field(min_length=3, max_length=500)


class BasicsDraft(BaseModel):
    answered: bool = Field(description="false if the articles don't actually answer the question")
    answer: str = Field(description="the answer, using only what the articles say", max_length=1500)
    source_slugs: list[str] = Field(default_factory=list, description="slugs of the articles the answer uses")


class BasicsAnswer(BaseModel):
    answer: str
    answered: bool
    redirected_to_professional: bool = False
    sources: list[dict] = []
    review_note: str | None = None


basics_agent = Agent(
    name="basics",
    deps_type=AgentDeps,
    output_type=BasicsDraft,
    instructions=load_prompt("basics"),
    retries=2,
)


@basics_agent.tool
async def search_basics_kb(ctx: RunContext[AgentDeps], query: str) -> dict:
    """Keyword search of the Fitness Basics articles. The only source you may answer from."""
    result = await ctx.deps.gateway.call("search_basics_kb", {"query": query})
    ctx.deps.seen.setdefault("articles", {}).update({a["slug"]: a for a in result["matches"]})
    return result


@basics_agent.output_validator
async def _check(ctx: RunContext[AgentDeps], draft: BasicsDraft) -> BasicsDraft:
    if not draft.answered:
        return draft
    seen = ctx.deps.seen.get("articles", {})
    unsupported = (not draft.source_slugs or any(s not in seen for s in draft.source_slugs)
                   or (not any(seen[s]["citations"] for s in draft.source_slugs) and makes_science_claim(draft.answer)))
    if unsupported and ctx.retry >= ctx.max_retries:   # out of retries: fall back to "no verified information"
        return draft.model_copy(update={"answered": False, "source_slugs": []})
    if not draft.source_slugs or any(s not in seen for s in draft.source_slugs):
        raise ModelRetry(f"source_slugs must list the articles you used, from: {sorted(seen)}.")
    if not any(seen[s]["citations"] for s in draft.source_slugs) and makes_science_claim(draft.answer):
        raise ModelRetry("These articles have no citations, so don't say anything is scientifically proven or "
                         "backed by research. Say what the guide says, plainly.")
    return draft


def no_info() -> BasicsAnswer:
    return BasicsAnswer(answer=NO_INFO_MESSAGE, answered=False)


def finalize(draft: BasicsDraft, deps: AgentDeps) -> BasicsAnswer:
    if not draft.answered:
        return no_info()
    if not any(deps.seen["articles"][s]["citations"] for s in draft.source_slugs) and makes_science_claim(draft.answer):
        return no_info()   # the validator already asked for a rewrite; never ship an unsupported claim
    sources = [{k: deps.seen["articles"][s][k] for k in ("slug", "title", "status", "review_notice", "citations")}
               for s in dict.fromkeys(draft.source_slugs)]
    pending = any(s["status"] == "placeholder" for s in sources)
    return BasicsAnswer(answer=draft.answer.strip(), answered=True, sources=sources,
                        review_note=PENDING_NOTE if pending else None)


async def answer_question(user_id: int, question: str, route: str,
                          clinical_review: bool = False) -> tuple[BasicsAnswer, dict]:
    # 1. Red-flag pre-filter: code only. The agent is never called for these questions.
    flags = red_flags_in(question)
    if flags:
        event_id = log_safety_event(user_id, "basics_qa", question)
        return (BasicsAnswer(answer=REDIRECT_MESSAGE, answered=False, redirected_to_professional=True),
                {"safety_event_id": event_id, "red_flags": flags, "agent_called": False})

    # Pregnant / postpartum: no AI answers (they need individual clinical clearance). Code reply, no model call.
    if clinical_review:
        return (BasicsAnswer(answer=CLINICAL_REVIEW_NO_AI, answered=False),
                {"agent_called": False, "needs_clinical_review": True, "page": CLINICAL_REVIEW_PAGE})

    deps = AgentDeps(gateway=McpGateway(), user_id=user_id)
    # 2. Nothing relevant in the knowledge base: say so without calling the model.
    pre = await deps.gateway.call("search_basics_kb", {"query": question}, called_by="code")
    if not pre["answerable"]:
        return no_info(), {"agent_called": False, "tool_calls": deps.gateway.calls}

    # 3. Let the agent answer from the knowledge base.
    draft, meta = await run_logged(basics_agent, agent_name="basics", deps=deps, route=route,
                                   prompt=f"Question: {question}")
    return finalize(draft, deps), {**meta, "agent_called": True}

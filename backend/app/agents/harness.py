"""Shared plumbing for the four agents: the model, the MCP gateway, prompts, and token logging.

Every agent reaches data ONLY through the MCP tool server (app/mcp_server/server.py), via McpGateway.
The gateway talks MCP to the server in-process (FastMCP's in-memory transport): same tools, same
validation, same read-only database connection, without starting a subprocess on every web request.
Claude Code uses the same server over stdio (.mcp.json).

Trust boundary: the model never supplies a user_id, injury flags, or checked_only. The agent code
fills those in from the signed-in session and the user's profile before any MCP call. See
backend/prompts/shared_rules.md, rules 2 and 4.
"""

import os
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from fastmcp import Client
from fastmcp.exceptions import ToolError
from openai import AsyncOpenAI
from pydantic_ai import Agent, ModelRetry
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RunUsage, UsageLimits

from app.config import MODEL_NAME, PORTKEY_BASE_URL, PROMPTS_DIR, get_secret
from app.db import connect

# Cost guards per agent call. Every agent here needs only a few tool calls.
USAGE_LIMITS = UsageLimits(request_limit=8, tool_calls_limit=12, total_tokens_limit=60_000)
MODEL_SETTINGS = ModelSettings(max_tokens=2000, timeout=90)


class AgentUnavailable(RuntimeError):
    """No API key is configured, so the AI features can't run."""


# ---------------------------------------------------------------- model

def _flagged_by_filter(exc: Exception) -> bool:
    """The provider's content filter sometimes flags an ordinary request ('invalid_prompt'). It's
    intermittent, so one retry of the same model usually goes through (same approach as HW5)."""
    return isinstance(exc, ModelHTTPError) and "invalid_prompt" in str(exc.body)


@lru_cache(maxsize=1)
def get_model() -> Model:
    """gpt-6-luna via Portkey; falls back to a direct OpenAI key if that's all that is set.
    Tests replace this function with a fake model, so no test ever calls the real API."""
    if key := get_secret("PORTKEY_API_KEY"):
        client = AsyncOpenAI(api_key="portkey", base_url=PORTKEY_BASE_URL,   # Portkey auths via the header
                             default_headers={"x-portkey-api-key": key, "x-portkey-provider": "openai"})
        provider = OpenAIProvider(openai_client=client)
    elif key := get_secret("OPENAI_API_KEY"):
        provider = OpenAIProvider(api_key=key)
    else:
        raise AgentUnavailable("No PORTKEY_API_KEY or OPENAI_API_KEY is set, so the AI features are off.")
    luna = OpenAIResponsesModel(MODEL_NAME, provider=provider)
    return FallbackModel(luna, luna, fallback_on=_flagged_by_filter)


# ---------------------------------------------------------------- prompts

def load_prompt(name: str) -> str:
    """backend/prompts/<name>.md with HTML comments (notes for developers) removed."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


# ---------------------------------------------------------------- MCP gateway

class McpGateway:
    """Calls the MCP tool server and keeps a trace of every call (shown in API responses and used by
    the agents' output checks). user_id never comes from the model: callers pass the session's id."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call(self, tool: str, args: dict[str, Any], *, called_by: str = "model") -> dict:
        from app.mcp_server.server import mcp   # imported here so the server module loads once, lazily

        shown = {k: ("(from your sign-in)" if k == "user_id" else v) for k, v in args.items()}
        entry = {"tool": tool, "args": shown, "called_by": called_by}
        self.calls.append(entry)
        try:
            async with Client(mcp) as client:
                result = await client.call_tool(tool, args)
        except ToolError as e:   # bad arguments: let the model see the message and try again
            entry["error"] = str(e)
            raise ModelRetry(f"{tool} rejected the arguments: {e}") from e
        return result.data


@dataclass
class AgentDeps:
    """Everything an agent run may use. Built by the route; the model can't change any of it."""
    gateway: McpGateway
    user_id: int | None                     # from the session token, set by the FastAPI route
    profile: dict | None = None             # PII-free profile from get_user_profile
    injury_flags: list[str] = field(default_factory=list)
    checked_only: bool = False              # True whenever injury_flags is non-empty (shared_rules rule 4)
    seen: dict[str, Any] = field(default_factory=dict)   # tool results, for the output checks


def harness_flags(profile: dict | None) -> tuple[list[str], bool]:
    """Injury flags and checked_only, decided by code from the profile (never by the model)."""
    flags = list(profile.get("injury_flags") or []) if profile and profile.get("found") else []
    return flags, bool(flags)


# ---------------------------------------------------------------- claims check (shared_rules rule 1)

SCIENCE_CLAIM = re.compile(
    r"\b(research|studies|study shows|scientific(ally)?|science[- ](says|shows|backed|based)|evidence[- ]based|"
    r"proven|clinically|peer[- ]reviewed|according to (experts|science))\b", re.I)


def makes_science_claim(text: str) -> bool:
    return bool(SCIENCE_CLAIM.search(text or ""))


# ---------------------------------------------------------------- run + token log

def _log_run(agent_name: str, user_id: int | None, route: str, usage: RunUsage, status: str,
             error_type: str | None, started: float) -> int:
    conn = connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO agent_runs (agent_name, user_id, input_tokens, output_tokens, cached_tokens, requests, "
                "tool_calls, model, route, status, error_type, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent_name, user_id, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
                 usage.requests, usage.tool_calls, MODEL_NAME, route, status, error_type,
                 round((time.perf_counter() - started) * 1000)))
        return cur.lastrowid
    finally:
        conn.close()


async def run_logged(agent: Agent, *, agent_name: str, prompt: str, deps: AgentDeps, route: str) -> tuple[Any, dict]:
    """Run an agent and write one agent_runs row with the measured tokens, success or failure.
    Returns (output, meta) where meta holds the run id, token usage, and the MCP tool-call trace."""
    usage = RunUsage()   # PydanticAI adds to this object as the run goes, so it's accurate even after an error
    started = time.perf_counter()
    model = get_model()
    try:
        result = await agent.run(prompt, deps=deps, model=model, usage=usage, usage_limits=USAGE_LIMITS,
                                 model_settings=MODEL_SETTINGS)
    except Exception as exc:
        _log_run(agent_name, deps.user_id, route, usage, "error", type(exc).__name__, started)
        raise
    run_id = _log_run(agent_name, deps.user_id, route, usage, "ok", None, started)
    return result.output, {
        "agent_run_id": run_id,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                  "cached_tokens": usage.cache_read_tokens, "requests": usage.requests,
                  "tool_calls": usage.tool_calls},
        "tool_calls": deps.gateway.calls,
    }

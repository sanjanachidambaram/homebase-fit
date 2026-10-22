"""Shared plumbing for the four agents: the model, the MCP gateway, prompts, and token logging.

Every agent reaches data ONLY through the MCP tool server (app/mcp_server/server.py), via McpGateway.
The gateway talks MCP to the server in-process (FastMCP's in-memory transport): same tools, same
validation, same read-only database connection, without starting a subprocess on every web request.
Claude Code uses the same server over stdio (.mcp.json).

Trust boundary: the model never supplies a user_id, injury flags, or checked_only. The agent code
fills those in from the signed-in session and the user's profile before any MCP call. See
backend/prompts/shared_rules.md, rules 2 and 4.
"""

import json
import os
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from functools import lru_cache
from typing import Any

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

from fastmcp import Client
import httpx2 as httpx   # the HTTP library the OpenAI SDK is built on (DefaultAsyncHttpxClient)
from fastmcp.exceptions import ToolError
from openai import AsyncOpenAI, DefaultAsyncHttpxClient
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
from app.safety_rules import checked_only_for

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


# ---------------------------------------------------------------- gateway cache detection
#
# The Portkey gateway on the course key replays a stored answer when it sees an identical request
# (checked 2026-10-22: the replay has the same response id and created_at as the original). It sends
# no cache header, so replays are detected from the response itself: a fresh answer is created after
# the gateway receives the request, so a created_at clearly OLDER than that moment means a replay.
# Replays cost no provider tokens, so agent_runs records them separately (see run_logged).

CACHE_TOLERANCE_S = 3.0      # clock differences plus the Date header's one-second resolution
_requests: ContextVar[list[dict] | None] = ContextVar("gateway_requests", default=None)


def is_gateway_replay(created_at: float | None, date_header: str | None, elapsed_s: float) -> bool | None:
    """True if the response was made before the gateway received the request (a cache replay),
    False if it's fresh, None if the response doesn't say."""
    if created_at is None or not date_header:
        return None
    try:
        received = parsedate_to_datetime(date_header).timestamp() - elapsed_s
    except (TypeError, ValueError):
        return None
    return created_at < received - CACHE_TOLERANCE_S


async def _mark_start(request: httpx.Request) -> None:
    request.extensions["homebase_started"] = time.monotonic()


async def _inspect_response(response: httpx.Response) -> None:
    """For the current agent run, record whether this model response was a replay, and its token usage."""
    calls = _requests.get()
    path = response.request.url.path
    if calls is None or not (path.endswith("/responses") or path.endswith("/chat/completions")):
        return
    entry: dict[str, Any] = {"status": response.status_code, "replay": None, "input_tokens": None,
                             "output_tokens": None}
    calls.append(entry)
    if response.status_code != 200:
        return
    try:
        body = json.loads(await response.aread())
    except (ValueError, httpx.HTTPError):
        return
    created = body.get("created_at", body.get("created"))
    elapsed = time.monotonic() - response.request.extensions.get("homebase_started", time.monotonic())
    entry["replay"] = is_gateway_replay(created, response.headers.get("date"), elapsed)
    usage = body.get("usage") or {}
    entry["input_tokens"] = usage.get("input_tokens", usage.get("prompt_tokens"))
    entry["output_tokens"] = usage.get("output_tokens", usage.get("completion_tokens"))


def gateway_http_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    """The HTTP client the model uses, with the hooks above. Tests pass a fake transport."""
    hooks = {"request": [_mark_start], "response": [_inspect_response]}
    return DefaultAsyncHttpxClient(event_hooks=hooks, **({"transport": transport} if transport else {}))


def summarize_gateway(calls: list[dict]) -> dict:
    """Roll one agent run's model requests up into the agent_runs cache columns."""
    known = [c for c in calls if c["replay"] is not None]
    hits = sum(1 for c in known if c["replay"])
    if not calls or len(known) < len(calls):
        status = "unknown"        # no model HTTP traffic seen (e.g. tests), or a response that couldn't be read
    elif hits == len(calls):
        status = "hit"
    elif hits == 0:
        status = "miss"
    else:
        status = "partial"
    fresh = [c for c in known if not c["replay"]]
    complete = status != "unknown" and all(c["input_tokens"] is not None for c in fresh)
    return {
        "gateway_cache_status": status,
        "gateway_cache_hits": hits,
        "fresh_input_tokens": sum(c["input_tokens"] or 0 for c in fresh) if complete else None,
        "fresh_output_tokens": sum(c["output_tokens"] or 0 for c in fresh) if complete else None,
    }


@lru_cache(maxsize=1)
def get_model() -> Model:
    """gpt-6-luna via Portkey; falls back to a direct OpenAI key if that's all that is set.
    Tests replace this function with a fake model, so no test ever calls the real API."""
    if key := get_secret("PORTKEY_API_KEY"):
        client = AsyncOpenAI(api_key="portkey", base_url=PORTKEY_BASE_URL,   # Portkey auths via the header
                             default_headers={"x-portkey-api-key": key, "x-portkey-provider": "openai"},
                             http_client=gateway_http_client())
    elif key := get_secret("OPENAI_API_KEY"):
        client = AsyncOpenAI(api_key=key, http_client=gateway_http_client())
    else:
        raise AgentUnavailable("No PORTKEY_API_KEY or OPENAI_API_KEY is set, so the AI features are off.")
    luna = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
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
    return flags, checked_only_for(flags)   # same rule as the program generator (app/safety_rules.py)


# ---------------------------------------------------------------- claims check (shared_rules rule 1)

SCIENCE_CLAIM = re.compile(
    r"\b(research|studies|study shows|scientific(ally)?|science[- ](says|shows|backed|based)|evidence[- ]based|"
    r"proven|clinically|peer[- ]reviewed|according to (experts|science))\b", re.I)


def makes_science_claim(text: str) -> bool:
    return bool(SCIENCE_CLAIM.search(text or ""))


# ---------------------------------------------------------------- run + token log

def _log_run(agent_name: str, user_id: int | None, route: str, usage: RunUsage, status: str,
             error_type: str | None, started: float, gateway: dict) -> int:
    conn = connect()
    try:
        # If the account was deleted while the model was running, still log the tokens, without the link.
        if user_id is not None and not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            user_id = None
        with conn:
            cur = conn.execute(
                "INSERT INTO agent_runs (agent_name, user_id, input_tokens, output_tokens, cached_tokens, requests, "
                "tool_calls, model, route, status, error_type, duration_ms, gateway_cache_status, gateway_cache_hits, "
                "fresh_input_tokens, fresh_output_tokens) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (agent_name, user_id, usage.input_tokens, usage.output_tokens, usage.cache_read_tokens,
                 usage.requests, usage.tool_calls, MODEL_NAME, route, status, error_type,
                 round((time.perf_counter() - started) * 1000), gateway["gateway_cache_status"],
                 gateway["gateway_cache_hits"], gateway["fresh_input_tokens"], gateway["fresh_output_tokens"]))
        return cur.lastrowid
    finally:
        conn.close()


async def run_logged(agent: Agent, *, agent_name: str, prompt: str, deps: AgentDeps, route: str) -> tuple[Any, dict]:
    """Run an agent and write one agent_runs row with the measured tokens, success or failure.
    Returns (output, meta) where meta holds the run id, token usage, and the MCP tool-call trace."""
    usage = RunUsage()   # PydanticAI adds to this object as the run goes, so it's accurate even after an error
    started = time.perf_counter()
    model = get_model()
    calls: list[dict] = []
    token = _requests.set(calls)   # the HTTP hook adds one entry per model request made during this run
    try:
        result = await agent.run(prompt, deps=deps, model=model, usage=usage, usage_limits=USAGE_LIMITS,
                                 model_settings=MODEL_SETTINGS)
    except Exception as exc:
        _log_run(agent_name, deps.user_id, route, usage, "error", type(exc).__name__, started,
                 summarize_gateway(calls))
        raise
    finally:
        _requests.reset(token)
    gateway = summarize_gateway(calls)
    run_id = _log_run(agent_name, deps.user_id, route, usage, "ok", None, started, gateway)
    return result.output, {
        "agent_run_id": run_id,
        "usage": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                  "cached_tokens": usage.cache_read_tokens, "requests": usage.requests,
                  "tool_calls": usage.tool_calls, **gateway},
        "tool_calls": deps.gateway.calls,
    }

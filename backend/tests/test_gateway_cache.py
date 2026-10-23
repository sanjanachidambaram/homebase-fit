"""Gateway cache replays are recorded in agent_runs, so the tokenomics numbers stay honest.

The end-to-end tests drive the REAL OpenAI Responses model class through a fake HTTP transport that
answers like the gateway: once with a fresh response, once with a replay of an old one.
"""

import json
import time
from email.utils import formatdate

import httpx2 as httpx   # the OpenAI SDK's HTTP library, so the fake transport fits its client
import pytest
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.agents import harness
from app.agents.harness import gateway_http_client, is_gateway_replay, summarize_gateway
from app.db import connect


def response_body(created_at: float) -> dict:
    """A minimal Responses API reply whose only output is the agent's final answer."""
    return {
        "id": f"resp_{int(created_at)}", "object": "response", "created_at": created_at, "model": "gpt-6-luna",
        "status": "completed", "error": None, "incomplete_details": None, "instructions": None, "metadata": {},
        "parallel_tool_calls": True, "temperature": 1, "top_p": 1, "tool_choice": "auto", "tools": [],
        "text": {"format": {"type": "text"}},
        "output": [{"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "final_result",
                    "status": "completed",
                    "arguments": json.dumps({"encouragement": "Nice work!", "fun_fact_comparison": None})}],
        "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150,
                  "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
    }


def fake_gateway(created_at_offset_s: float):
    """A model that talks to a fake gateway. offset 0 = fresh answer; -3600 = replay of an hour-old answer."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_body(time.time() + created_at_offset_s),
                              headers={"date": formatdate(usegmt=True)})
    client = AsyncOpenAI(api_key="test", base_url="http://gateway.test/v1",
                         http_client=gateway_http_client(httpx.MockTransport(handler)))
    return OpenAIResponsesModel("gpt-6-luna", provider=OpenAIProvider(openai_client=client))


def account(client) -> dict:
    r = client.post("/api/users", json={"username": "cache", "first_name": "Tester", "password": "correct horse 1"}).json()
    return {"Authorization": f"Bearer {r['token']}"}


def last_run() -> dict:
    conn = connect()
    try:
        return dict(conn.execute("SELECT * FROM agent_runs ORDER BY id DESC LIMIT 1").fetchone())
    finally:
        conn.close()


# ---------------------------------------------------------------- detection rule

def test_replay_rule():
    now = time.time()
    date_now = formatdate(now, usegmt=True)
    assert is_gateway_replay(now - 1, date_now, elapsed_s=2.0) is False      # made while we waited: fresh
    assert is_gateway_replay(now - 25, date_now, elapsed_s=30.0) is False    # long generation: still fresh
    assert is_gateway_replay(now - 600, date_now, elapsed_s=0.5) is True     # made 10 minutes earlier: replay
    assert is_gateway_replay(now - 10, date_now, elapsed_s=0.4) is True      # even a recent original is a replay
    assert is_gateway_replay(None, date_now, 1.0) is None and is_gateway_replay(now, None, 1.0) is None


def test_summary_of_a_run():
    fresh = {"replay": False, "input_tokens": 100, "output_tokens": 20}
    replay = {"replay": True, "input_tokens": 90, "output_tokens": 10}
    unknown = {"replay": None, "input_tokens": None, "output_tokens": None}
    assert summarize_gateway([fresh, fresh]) == {"gateway_cache_status": "miss", "gateway_cache_hits": 0,
                                                 "fresh_input_tokens": 200, "fresh_output_tokens": 40}
    assert summarize_gateway([replay, replay]) == {"gateway_cache_status": "hit", "gateway_cache_hits": 2,
                                                   "fresh_input_tokens": 0, "fresh_output_tokens": 0}
    assert summarize_gateway([replay, fresh]) == {"gateway_cache_status": "partial", "gateway_cache_hits": 1,
                                                  "fresh_input_tokens": 100, "fresh_output_tokens": 20}
    assert summarize_gateway([])["gateway_cache_status"] == "unknown"
    assert summarize_gateway([fresh, unknown])["fresh_input_tokens"] is None


# ---------------------------------------------------------------- end to end through the real model class

@pytest.mark.parametrize("offset, status, hits, fresh_in, fresh_out", [
    (0, "miss", 0, 120, 30),          # fresh answer: the provider really processed these tokens
    (-3600, "hit", 1, 0, 0),          # replay: tokens are reported but nothing was processed
])
def test_agent_runs_records_gateway_replays(client, monkeypatch, offset, status, hits, fresh_in, fresh_out):
    monkeypatch.setattr(harness, "get_model", lambda: fake_gateway(offset))
    r = client.get("/api/coach/summary", headers=account(client))
    assert r.status_code == 200, r.text
    assert r.json()["result"]["encouragement"] == "Nice work!"
    run = last_run()
    assert (run["gateway_cache_status"], run["gateway_cache_hits"]) == (status, hits)
    assert (run["fresh_input_tokens"], run["fresh_output_tokens"]) == (fresh_in, fresh_out)
    assert (run["input_tokens"], run["output_tokens"], run["requests"]) == (120, 30, 1)   # reported usage, as before
    assert r.json()["meta"]["usage"]["gateway_cache_status"] == status


def test_scripted_test_models_are_logged_as_unknown(client, monkeypatch):
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def fn(messages, info):
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name,
                                                 {"encouragement": "Hi!", "fun_fact_comparison": None})])
    monkeypatch.setattr(harness, "get_model", lambda: FunctionModel(fn))
    client.get("/api/coach/summary", headers=account(client))
    run = last_run()
    assert run["gateway_cache_status"] == "unknown" and run["fresh_input_tokens"] is None

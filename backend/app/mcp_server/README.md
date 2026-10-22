# HomeBase Fit MCP server

The FastMCP tool layer the AI agents call. It is separate from the REST API (`app/main.py`), which the website uses.
Exactly **7 tools**, all **read-only**. There is no delete tool, no write tool, and nothing that returns an email.

| # | Tool | What it does |
|---|---|---|
| 1 | `get_user_profile(user_id)` | goals, timeline, injury_flags, age, weight_lb, height_in. Nothing else. Uses `agents/context.py` |
| 2 | `search_exercises(muscle_group, equipment, injury_flags, limit, checked_only)` | Exercise library. Injury filter is in the SQL. Untagged exercises are flagged `not_yet_checked` |
| 3 | `search_program_templates(goal_tags, injury_flags)` | Program templates, best goal match first; a program is dropped if any exercise is unsafe for a flag |
| 4 | `search_basics_kb(query)` | Keyword search over Fitness Basics. The only source for answering basics questions |
| 5 | `get_progress_summary(user_id)` | Last 30 days: sessions, weight lifted, streak, measurement trends |
| 6 | `compute_strength_equivalents(total_weight_lifted_lbs)` | Fun comparisons with real weights and sources. No database |
| 7 | `check_goal_achievement(user_id)` | `on_track` / `ahead` / `behind` / `insufficient_data` from the progress and the quiz goals |

## Run it

From the project root (this is what `.mcp.json` does):

```bash
backend/.venv/Scripts/python.exe backend/app/mcp_server/server.py
```

It talks MCP over stdio, so on its own it just waits for a client. To check it works end to end:

```bash
backend/.venv/Scripts/python.exe backend/app/mcp_server/smoke_test.py
```

The smoke test launches the server from `.mcp.json`, calls all 7 tools, and proves the injury filter removes a
tagged exercise. It uses a throwaway copy of the database (via `HOMEBASE_DB_PATH`), so no committed data is touched.

## Connecting Claude Code

`.mcp.json` at the project root registers the server as `homebase-fit`. Claude Code reads it when a session starts and
asks you to approve a project server the first time, so open a new session in this folder, approve it, and check
`/mcp`. The tools then appear as `mcp__homebase-fit__<tool name>`.

## Guardrails (and where they live)

- **Read-only:** the tools open SQLite with `mode=ro` (`app/db/__init__.py: connect_readonly`), so even a wrong query
  cannot change data. All tools carry the MCP `readOnlyHint`. A test asserts the tool list is exactly these 7.
- **Injury filter:** `search.py`, `NOT_CONTRAINDICATED`. The model can't switch it off; the agent harness supplies the flags.
- **Honest about unchecked exercises:** most exercises have no injury tags. They come back with
  `injury_check: "not_yet_checked"` and a note saying so. `checked_only=true` returns only tagged ones.
- **No PII:** `get_user_profile` calls `agent_profile_for`, the same function the agents use for prompts.
- **Citation fields:** every exercise, program, and article carries `status`, `review_notice`, and `citations`.

## Equipment, in one sentence

`equipment` is what the user **has**. A result needs only items from that list (bodyweight exercises always qualify),
so `["dumbbells"]` returns dumbbell and bodyweight exercises. Leave it out to ignore equipment.

## The goal check is a heuristic

`check_goal_achievement` uses simple thresholds listed in `progress.py: THRESHOLDS` and echoed in every result.
They are placeholders for the PT to review, not science. How it decides:

1. Fewer than 7 days since the quiz: `insufficient_data`.
2. Consistency (every goal): sessions per week vs a target by timeline (4 weeks: 4, 8 or 12 weeks: 3, no deadline: 2).
   At least 125% of target is `ahead`, at least 75% is `on_track`, below that is `behind`.
3. `weight_loss`: body weight down over 7+ days is `on_track`; flat or up is `behind` (it can't say `ahead`, because
   no target weight is stored). `strength`: weight lifted in the last 15 days vs the 15 before. `tone` and `rehab`
   can't be measured from the logs, so they're judged on consistency only.
4. Overall: `behind` if any check is behind; `ahead` only if every judged check is ahead; otherwise `on_track`.

## For the agent harness (next step)

Three tools take a `user_id` and this server can't tell who is asking. The harness must set `user_id` from the signed-in
session and hide it from the model. See `backend/prompts/shared_rules.md`, rules 2 and 4.

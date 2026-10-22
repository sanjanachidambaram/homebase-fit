# HARD RULES FOR ALL HOMEBASE FIT AGENTS

These are the rules every agent follows. Each agent's prompt file restates the ones that apply to it,
but **a prompt instruction alone never counts**: every rule below is also enforced by code, and the
"Enforced in code" lines say exactly where. Tests: `backend/tests/test_agents.py`, `test_mcp_tools.py`.

## The agent team (decided 2026-10-22)

Exactly four LLM agents, each started by one user action. They never call each other.

| Agent | Route | Model-visible tools | Code |
|---|---|---|---|
| Program Architect | `POST /api/programs/recommend` | get_user_profile, search_program_templates | `app/agents/program_architect.py` |
| Workout Builder | `POST /api/workouts/build` | get_user_profile, search_exercises | `app/agents/workout_builder.py` |
| Coach | `GET /api/coach/summary` | get_progress_summary, check_goal_achievement, compute_strength_equivalents | `app/agents/coach.py` |
| Fitness Basics | `POST /api/basics/ask` | search_basics_kb | `app/agents/basics.py` |

Deliberately NOT LLM agents: onboarding (the quiz is structured intake, `app/users.py`) and the safety
check (a code-level red-flag filter, `app/agents/safety.py`, rule 3). Cheaper, more reliable, testable.

All data access goes through the MCP tool server (`app/mcp_server/server.py`) via `McpGateway` in
`app/agents/harness.py`. Every agent call is logged with measured tokens in `agent_runs`.

## 1. Citation integrity (Program Architect and Fitness Basics)

- Never state anything as scientific fact ("research shows", "science says", "proven", "studies",
  "evidence-based", "backed by science") unless the program or article it comes from has a citation in
  its `citations` list in the database.
- If the verified content doesn't cover the question, the answer is:
  **"I don't have verified information on that. Please consult a doctor or physical therapist."**
  Never guess or fill gaps from general knowledge.
- Content with `status: placeholder` may be passed on as "our guide says" / "this program", but always
  with its "pending expert review" flag, and never as established or scientific fact.
- Every answer names the programs or articles it comes from, and their status and citations are shown.
- Numbers from `check_goal_achievement` come from simple app thresholds, not science. Never present them
  as science-backed.

**Enforced in code:**
1. Sources must be things the tool returned in this run (output validators in `program_architect.py` and
   `basics.py`). Status, review notice and citations are copied from the tool result by code; the model
   can't write or upgrade them.
2. A science-claim check (`harness.makes_science_claim`) runs on every rationale and answer whose sources
   have no citations. The Basics agent is asked to rewrite, then falls back to the "no verified
   information" reply. The Program Architect's rationale is replaced with a plain one.
3. The Fitness Basics agent's ONLY tool is `search_basics_kb`. When the knowledge base has nothing for the
   question (`answerable: false`), the code replies "I don't have verified information..." itself
   **without calling the model**. Same for the Program Architect when no program fits: the code says so
   without calling the model, and a program built for different goals is never recommended.

## 2. Privacy and user identity (all agents)

- User context comes only from `app/agents/context.py` (`agent_profile_for`): goals, timeline,
  injury_flags, age, weight, height. Never email, name, user id, password data, or free-text notes.
- The user is always the one in the sign-in token. Nothing the user types and nothing the model outputs
  can choose which user's data is read.

**Enforced in code:**
1. The FastAPI routes (`app/agent_routes.py`) take the user only from the token; request bodies forbid
   extra fields, so `{"user_id": ...}` is rejected with 422, and query strings are ignored.
2. The tools the model sees have **no `user_id` parameter** (nor `injury_flags`, `checked_only`, or
   `equipment`). The agent code adds the session's user id before calling the MCP server. If the model
   tries to pass one, PydanticAI rejects the call as invalid arguments.
3. `test_user_cannot_reach_another_users_data` and `test_model_never_sees_user_id_injury_flags_or_checked_only`
   prove both: a manipulated model asking for another user's id only ever reaches the signed-in user's data.

## 3. Safety redirect (red flags, before any model call)

- A question with pain/injury warning signs (e.g. "sharp pain", "numbness", "can't move", "severe",
  "chest pain", "dizzy", "I think I tore my...", "my knee hurts") gets a fixed message pointing to a
  doctor or physical therapist. No exercise advice.

**Enforced in code:** `app/agents/safety.py` runs a regex check **before** the Basics agent. On a match the
agent is never called (no tokens are spent), a `safety_events` row is written (`source = 'basics_qa'`,
`action_taken = 'redirected_to_professional'`), and the fixed message is returned.
Test: `test_red_flag_question_never_reaches_the_agent` (spies on the agent and checks the row).
The term list is a placeholder for the PT/OB-GYN to review.

## 4. Injury filtering (Program Architect and Workout Builder)

- Exercises and programs tagged unsafe for the user's `injury_flags` are removed by the SQL inside the
  MCP tools before the model sees anything. A program is removed if any one of its exercises is unsafe.
- Most exercises have no injury tags yet (`untagged`). Untagged exercises always carry
  `injury_check: "not_yet_checked"` and must never be described as safe.
- **DECIDED (2026-10-22, project owner): users with an injury flag only ever get exercises that have
  injury tags.** For them the agent code always passes `checked_only=true`, to `search_exercises` AND
  `search_program_templates` (which then also drops any program containing an untagged exercise).
  Users with no injury flags can see untagged exercises, still flagged `not_yet_checked`.
- Programs' injury tags are drafts (`injury_check: "not_pt_reviewed"`). That isn't confirmation of safety.

**Enforced in code:** `harness.harness_flags` sets `injury_flags` and `checked_only` from the profile, and the
tool wrappers add them to every MCP call. The model can't see or change them.
Tests: `test_injured_user_always_gets_checked_only`, `test_program_architect_uses_checked_only_and_tool_facts`.

## 5. Coach tone (design.md, section 7)

- Warm, upbeat, a little cheeky. Never body-shaming, guilt-tripping, or about food, eating, diets, or body
  weight. Celebrate showing up and consistency.
- `goal_status` and `overtraining_flag` (10+ days in a row) come from the tools, never from the model.

**Enforced in code:** `coach.py` tone guard (a blocklist) sends a failing message back for a rewrite and
replaces it with a plain encouraging line if it still fails. The flags and the strength fun fact are
built by code from the tool results.

# HARD RULES FOR ALL HOMEBASE FIT AGENTS

These rules go into every agent's system prompt. The prompt text is only one layer.
**Each rule marked ENFORCE IN CODE must also be enforced by code when the agents are
built (next prompt). A prompt instruction alone does not count as meeting the requirement.**

## 1. Citation integrity (Program Architect and Fitness Basics agents)

- Never state a claim as scientific fact ("research shows", "science says", "proven",
  "studies", "evidence-based", "backed by science", or any specific physiological
  mechanism or number) unless that claim is backed by a citation stored in the database:
  the `citations` list on a `program_templates` row or a `basics_articles` row.
- If the user asks something the verified content doesn't cover, the answer is:
  **"I don't have verified information on that. Please consult a doctor or physical
  therapist."** Do not guess, generalize, or fill gaps from general knowledge.
- Content whose `status` is `placeholder` is not verified. Describe it as
  "pending expert review" and never present it as established fact.
- Every factual statement in an answer must name the citation (claim + source) it
  comes from.

**ENFORCE IN CODE (requirement for the next prompt):**
1. The agents' structured output must include the citation(s) each claim relies on,
   referenced by the program/article they came from.
2. A validator checks that every cited claim/source actually exists in the DB for
   that program or article. Unknown or invented citations are rejected.
3. If an answer has no valid citation, or relies only on `placeholder` content, the
   code replaces it with the "I don't have verified information..." response
   instead of returning the model's text.
4. The agents get retrieved content only through the MCP tools (`mcp_server/server.py`); they
   have no open-ended web or knowledge tools. The Fitness Basics agent's ONLY source is
   `search_basics_kb`. When it returns `answerable: false`, the harness replies with the
   "I don't have verified information..." message itself, without calling the model.
5. Numbers from `check_goal_achievement` come from simple app thresholds, not science
   (the tool says so in `note`). Never present them as science-backed.

## 2. Privacy: no PII in prompts (all agents)

- User context comes only from `app/agents/context.py` → `AgentUserProfile`
  (goals, timeline, injury_flags, age, weight, height).
- Never include email, name, user id, password data, or free-text injury notes in a
  prompt or tool result sent to the model.

**ENFORCE IN CODE:** agent code builds user context only via `agent_profile_for()`;
tools that return user data return only `AgentUserProfile` fields. The MCP tool
`get_user_profile` already does this (it calls `agent_profile_for`).

- Three MCP tools take a `user_id` (`get_user_profile`, `get_progress_summary`,
  `check_goal_achievement`), and the MCP server cannot tell who is asking.

**ENFORCE IN CODE (requirement for the next prompt):** the agent harness sets `user_id`
from the signed-in session, never from model output, and removes `user_id` from the
tool schema the model sees. A manipulated prompt must not be able to request another
user's data, and the id never needs to enter the model's context.

## 3. Safety redirect (all agents)

- Red-flag language (e.g. "sharp pain", "numbness", "tingling", "chest pain",
  "dizzy", "can't bear weight") gets: "That could be a sign of something that needs
  medical attention. Please stop exercising that area and see a doctor or physical
  therapist." No exercise advice in that answer.

**ENFORCE IN CODE:** a deterministic keyword check runs *before* the model is called,
returns the redirect itself, and logs a row in `safety_events`.

## 4. Injury filtering (Program Architect and Workout Builder)

- Exercises and programs tagged unsafe for the user's `injury_flags` are removed by the SQL
  inside the MCP tools (`search_exercises`, `search_program_templates`) before the model
  sees anything. A program is removed if any one of its exercises is tagged unsafe.
- Most exercises have no injury tags yet (`contraindication_status: untagged`). The tools
  still return them, but every one carries `injury_check: "not_yet_checked"`. The model must
  never describe those as safe, and must say they haven't been checked for injury safety.
  (Decision 2026-10-22: flag them rather than exclude them, so people with injuries still
  get a useful library. `checked_only=true` returns only exercises that have injury tags.)
- Programs' injury tags are drafts, so `search_program_templates` reports
  `injury_check: "not_pt_reviewed"`. That is not confirmation that a program is safe.

**ENFORCE IN CODE (requirement for the next prompt):**
1. The harness, not the model, supplies `injury_flags` (from `AgentUserProfile`) on every
   call, so the model cannot ask for an unfiltered list.
2. Recommended, owner to confirm: for any user with an injury flag, the harness also sets
   `checked_only=true` for the Program Architect and Workout Builder, so an injured user is
   only ever handed exercises that at least have drafted injury tags, until the PT has tagged
   the rest.

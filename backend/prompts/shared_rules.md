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
4. The agents get retrieved content only through MCP/DB tools; they have no
   open-ended web or knowledge tools.

## 2. Privacy: no PII in prompts (all agents)

- User context comes only from `app/agents/context.py` → `AgentUserProfile`
  (goals, timeline, injury_flags, age, weight, height).
- Never include email, name, user id, password data, or free-text injury notes in a
  prompt or tool result sent to the model.

**ENFORCE IN CODE:** agent code builds user context only via `agent_profile_for()`;
tools that return user data return only `AgentUserProfile` fields.

## 3. Safety redirect (all agents)

- Red-flag language (e.g. "sharp pain", "numbness", "tingling", "chest pain",
  "dizzy", "can't bear weight") gets: "That could be a sign of something that needs
  medical attention. Please stop exercising that area and see a doctor or physical
  therapist." No exercise advice in that answer.

**ENFORCE IN CODE:** a deterministic keyword check runs *before* the model is called,
returns the redirect itself, and logs a row in `safety_events`.

## 4. Injury filtering (Program Architect and Workout Builder)

- Exercises contraindicated for the user's `injury_flags` are removed by a DB/tool
  filter before the model sees the list. For users with any injury flag, exercises
  whose `contraindication_status` is `untagged` are excluded too.

**ENFORCE IN CODE:** the tool query does the filtering; the model can't request
unfiltered exercises.

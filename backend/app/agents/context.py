"""The ONLY way user data may enter an agent / LLM prompt.

=============================================================================
PRIVACY RULE (PII never reaches the model) -- referenced in the report's
safety section.

Every agent call that needs to know about the user MUST build its user context
with `agent_profile_for(user_id)` below and pass the resulting
`AgentUserProfile` (or its `.to_prompt_json()`) to the model. Never pass a
users row, a quiz_profiles row, or a request body straight into a prompt.

`AgentUserProfile` contains two structured fields only: goal and injury_flags
(since the 2026-10-25 quiz rewrite; age, height, timeline and weight are gone from
it). It deliberately EXCLUDES (EXCLUDED_USER_FIELDS below, checked when this module
loads):
  - username, first_name, email and password_hash (identify the person)
  - user id (links model-provider logs back to our database)
  - injury_notes (free text; no longer asked since 2026-10-25, and the column is gone,
    but kept on the list so it can't come back into a prompt unnoticed)
  - weight and goal_weight (body measurements; used only by code, for calorie math)
The SQL below selects only the allowed columns and never joins `users`, and
the model forbids extra fields, so PII can't slip in by accident.
=============================================================================
"""

import json

from pydantic import BaseModel, ConfigDict

from app.db import Connection, connect


class AgentUserProfile(BaseModel):
    """What an agent may know about the user. Adding a field here is a privacy
    decision: it must never be identifying (nothing in EXCLUDED_USER_FIELDS, and no free text)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: str                 # stronger | lose_weight | feel_good
    injury_flags: list[str]

    def to_prompt_json(self) -> str:
        return self.model_dump_json()


ALLOWED_COLUMNS = "goal, injury_flags"

# Identifying fields that must never reach any agent, its prompt, or an MCP tool result. "email" stays listed
# although sign-in now uses a username: accounts from before 2026-10-23 have their old email as their username.
EXCLUDED_USER_FIELDS = frozenset({"username", "first_name", "name", "email", "password_hash", "user_id", "id",
                                  "injury_notes", "weight", "weight_lb", "goal_weight"})
_allowed = {c.strip() for c in ALLOWED_COLUMNS.split(",")}
assert not (_allowed | set(AgentUserProfile.model_fields)) & EXCLUDED_USER_FIELDS, \
    "an excluded (identifying) field was added to the agent profile"


def agent_profile_for(user_id: int, conn: Connection | None = None) -> AgentUserProfile | None:
    """The PII-free profile for a user, or None if they haven't taken the quiz.
    user_id is used only for this local lookup; it is not part of the result.

    This is the single source of truth for what an agent may know about a user: the MCP tool
    get_user_profile calls it too (passing its read-only connection), so there is no second copy
    of the field list to drift out of sync."""
    own_conn = conn is None
    conn = conn or connect()
    try:
        row = conn.execute(f"SELECT {ALLOWED_COLUMNS} FROM quiz_profiles WHERE user_id = ?", (user_id,)).fetchone()
    finally:
        if own_conn:
            conn.close()
    if row is None:
        return None
    return AgentUserProfile(goal=row["goal"], injury_flags=json.loads(row["injury_flags"]))

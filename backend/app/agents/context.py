"""The ONLY way user data may enter an agent / LLM prompt.

=============================================================================
PRIVACY RULE (PII never reaches the model) -- referenced in the report's
safety section.

Every agent call that needs to know about the user MUST build its user context
with `agent_profile_for(user_id)` below and pass the resulting
`AgentUserProfile` (or its `.to_prompt_json()`) to the model. Never pass a
users row, a quiz_profiles row, or a request body straight into a prompt.

`AgentUserProfile` contains structured fields only: goals, timeline,
injury_flags, age, weight, height. It deliberately EXCLUDES:
  - email and password_hash (identify the person)
  - user id (links model-provider logs back to our database)
  - injury_notes (free text; people type names, doctors, diagnoses, etc.)
The SQL below selects only the allowed columns and never joins `users`, and
the model forbids extra fields, so PII can't slip in by accident.
=============================================================================
"""

import json

from pydantic import BaseModel, ConfigDict

from app.db import connect


class AgentUserProfile(BaseModel):
    """What an agent may know about the user. Adding a field here is a privacy
    decision: it must never be identifying (no email, name, id, or free text)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goals: list[str]
    timeline: str | None
    injury_flags: list[str]
    age: int | None
    weight_lb: float | None
    height_in: float | None

    def to_prompt_json(self) -> str:
        return self.model_dump_json()


ALLOWED_COLUMNS = "goals, timeline, injury_flags, age, weight, height"


def agent_profile_for(user_id: int) -> AgentUserProfile | None:
    """The PII-free profile for a user, or None if they haven't taken the quiz.
    user_id is used only for this local lookup; it is not part of the result."""
    conn = connect()
    try:
        row = conn.execute(f"SELECT {ALLOWED_COLUMNS} FROM quiz_profiles WHERE user_id = ?", (user_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return AgentUserProfile(
        goals=json.loads(row["goals"]),
        timeline=row["timeline"],
        injury_flags=json.loads(row["injury_flags"]),
        age=row["age"],
        weight_lb=row["weight"],
        height_in=row["height"],
    )

"""Wipe all user data (a clean demo database). The content tables and the agent_runs token log are kept.

Run from backend/:
    .venv\\Scripts\\python.exe -m app.db.reset

Always kept: the agent_runs token log. It's the measurement record for the tokenomics report; its user_id is cleared,
since the accounts are gone. (Reloading CONTENT never touches accounts at all: that's app/db/seed.py.)

USER_TABLES, RENAMED_COLUMNS and migrate_quiz_profile describe older versions of the user data. The one-time import
from the old SQLite database (app/db/import_sqlite.py) uses them to bring rows saved under an older schema across.
"""

import json

from app.db import connect, table_counts

# Columns renamed between schema versions, {table: {new name: old name}}: when the saved rows predate the rename,
# the new column is filled from the old one. 2026-10-23: sign-in moved from email to username, and existing
# accounts keep their old email as their username, so nobody is locked out.
RENAMED_COLUMNS = {"users": {"username": "email"}}


def migrate_quiz_profile(row: dict) -> dict:
    """2026-10-25 quiz rewrite: several goals -> one goal, and only the weight-loss path keeps a weight. Profiles saved
    before it are carried over instead of dropped: weight_loss among the goals -> lose_weight; strength or tone ->
    stronger; anything else (rehab, general health) -> feel_good. Weight and goal weight are kept only for lose_weight
    (the new schema refuses them otherwise). Equipment keeps only answers the new quiz still offers, and bodyweight
    is always included. Review-mode swaps are cleared (they belonged to the old plan). The removed answers (timeline,
    days, session length, other activity, age, height, goal date) simply aren't copied."""
    if "goal" in row or "goals" not in row:
        return row
    old = set(json.loads(row.get("goals") or "[]"))
    goal = "lose_weight" if "weight_loss" in old else "stronger" if old & {"strength", "tone"} else "feel_good"
    equipment = [e for e in json.loads(row.get("equipment") or "[]")
                 if e in ("bodyweight", "dumbbells", "kettlebells", "resistance_band", "mat", "full_gym")]
    out = {**row, "goal": goal, "equipment": json.dumps(sorted(set(equipment) | {"bodyweight"})),
           "plan_swaps": "{}", "plan_reviewed": 0}
    if goal != "lose_weight":
        out["weight"] = out["goal_weight"] = None
    return out


# Per-table row migrations for rows saved under an older schema.
ROW_MIGRATIONS = {"quiz_profiles": migrate_quiz_profile}

# Parents first, so ids line up. (app/users.py USER_DATA_TABLES lists the same tables for account deletion.)
USER_TABLES = ("users", "quiz_profiles", "exercise_favorites", "measurements", "calendar_entries", "cardio_logs",
               "built_workouts", "workout_logs", "safety_events")


def reset() -> int:
    """Wipe all user data; returns how many agent_runs rows were kept (with user_id cleared)."""
    conn = connect()
    try:
        with conn:
            # Not TRUNCATE ... CASCADE: that would empty agent_runs too (it references users). Deleting the users lets
            # each foreign key do its job: user data cascades away, agent_runs.user_id is set to NULL.
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM safety_events")   # anonymous events (user_id NULL) aren't anyone's to cascade
            kept = conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
    finally:
        conn.close()
    return kept


if __name__ == "__main__":
    kept = reset()
    print(f"Wiped all user data (kept {kept} agent_runs rows).")
    conn = connect()
    try:
        counts = table_counts(conn)
    finally:
        conn.close()
    for table, n in counts.items():
        print(f"  {table:28} {n}")

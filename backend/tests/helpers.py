"""Shared test data."""


def quiz_answers(**overrides) -> dict:
    """A complete, valid set of answers for the current quiz (content/quiz/quiz_questions.yaml): the losing-weight path,
    so weight and goal weight are asked. For another goal, pass goal=... (weight is then ignored unless you drop it)."""
    answers = {
        "goal": "lose_weight", "experience_level": "beginner",
        "equipment": ["bodyweight", "mat", "resistance_band"], "injuries": ["lower_back"], "pregnancy_status": "none",
        "weight": 165, "goal_weight": 155,
    }
    answers.update(overrides)
    if answers.get("goal") != "lose_weight":   # only asked on the losing-weight path
        answers.pop("weight", None)
        answers.pop("goal_weight", None)
    return answers


def db_snapshot() -> dict[str, str]:
    """A hash of every table's full contents in the test database, to prove something wrote nothing."""
    from app.db import connect, table_counts
    conn = connect()
    try:
        return {t: conn.execute(f"SELECT md5(COALESCE(string_agg(x::text, '|' ORDER BY x::text), '')) "
                                f'FROM "{t}" x').fetchone()[0] for t in table_counts(conn)}
    finally:
        conn.close()

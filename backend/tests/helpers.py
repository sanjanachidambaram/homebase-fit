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

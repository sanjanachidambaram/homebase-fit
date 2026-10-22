"""Shared test data."""


def quiz_answers(**overrides) -> dict:
    """A complete, valid set of answers for the current quiz (content/quiz/quiz_questions.yaml)."""
    answers = {
        "goals": ["weight_loss", "rehab"], "timeline": "8_weeks", "experience_level": "beginner",
        "days_available": 4, "session_length": "30", "equipment": ["bodyweight", "mat", "resistance_band"],
        "other_activity_days": 0, "injuries": ["lower_back"], "pregnancy_status": "none",
        "age": 34, "weight": 165, "height": 66,
    }
    answers.update(overrides)
    return answers

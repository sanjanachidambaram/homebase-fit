"""Safety decisions shared by the program generator and the agents, so they can never disagree.
See backend/prompts/shared_rules.md, rule 4.
"""

# Head to toe. Every hand-authored exercise has been considered for every flag here (its tags are drafted, then
# PT-reviewed), so adding a flag means drafting it across content/exercises/*/exercises.yaml too.
# neck, upper_back and hip were added 2026-10-23.
INJURY_FLAGS = ("neck", "shoulder", "upper_back", "lower_back", "wrist", "hip", "knee", "ankle")
CLINICAL_REVIEW_STATUSES = ("pregnant", "postpartum")

# Why an exercise carries an injury tag (exercises.injury_rationale). Every rationale is ai_drafted until a
# licensed PT confirms it; then tier becomes pt_reviewed and source becomes her name and credentials.
# The reasoning is general exercise science, never an invented citation.
RATIONALE_TIERS = ("ai_drafted", "pt_reviewed")
RATIONALE_PENDING_SOURCE = "Pending review by a licensed physical therapist"


def checked_only_for(injury_flags: list[str] | None) -> bool:
    """DECIDED 2026-10-22: anyone with an injury flag only ever gets exercises that have injury tags.
    No exceptions, no override."""
    return bool(injury_flags)


def needs_clinical_review(pregnancy_status: str | None) -> bool:
    """Pregnant and postpartum users need OB-GYN-reviewed guidance; until it exists, no plan is generated."""
    return pregnancy_status in CLINICAL_REVIEW_STATUSES


# Where pregnant / postpartum users are sent instead of any AI feature (frontend route).
CLINICAL_REVIEW_PAGE = "/pregnancy-support"
CLINICAL_REVIEW_NO_AI = (
    "While you're pregnant or postpartum, HomeBase Fit's AI features and generated workouts are switched off, "
    "because exercise in this period needs individual clearance from a clinician who knows you. Please talk with "
    "your OB-GYN or midwife."
)


def profile_needs_clinical_review(user_id: int) -> bool:
    """True if this user's quiz says pregnant or postpartum (the generated needs_clinical_review column)."""
    from app.db import connect_readonly   # local import: this module stays free of DB imports for the generator

    conn = connect_readonly()
    try:
        row = conn.execute("SELECT needs_clinical_review FROM quiz_profiles WHERE user_id = ?", (user_id,)).fetchone()
    finally:
        conn.close()
    return bool(row and row[0])

"""Safety decisions shared by the program generator and the agents, so they can never disagree.
See backend/prompts/shared_rules.md, rule 4.
"""

INJURY_FLAGS = ("lower_back", "knee", "shoulder", "wrist", "ankle")
CLINICAL_REVIEW_STATUSES = ("pregnant", "postpartum")


def checked_only_for(injury_flags: list[str] | None) -> bool:
    """DECIDED 2026-10-22: anyone with an injury flag only ever gets exercises that have injury tags.
    No exceptions, no override."""
    return bool(injury_flags)


def needs_clinical_review(pregnancy_status: str | None) -> bool:
    """Pregnant and postpartum users need OB-GYN-reviewed guidance; until it exists, no plan is generated."""
    return pregnancy_status in CLINICAL_REVIEW_STATUSES

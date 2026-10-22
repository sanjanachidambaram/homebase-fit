"""Helpers shared by the routes that serve content (exercises, programs, articles)."""

import json

from app.config import PROJECT_ROOT

# Shown on any content whose status is still 'placeholder', so no UI can
# present unreviewed content as if it were verified.
REVIEW_NOTICE = "Content pending expert review"


def media_url(path: str | None) -> str | None:
    """URL for a media file (DB paths are project-relative and served under /content),
    or None if the file isn't there yet."""
    return f"/{path}" if path and (PROJECT_ROOT / path).is_file() else None


def review_info(row) -> dict:
    """status + citations + the pending-review flag, for any row that has them."""
    return {
        "status": row["status"],
        "review_notice": REVIEW_NOTICE if row["status"] == "placeholder" else None,
        "citations": json.loads(row["citations"]),
    }

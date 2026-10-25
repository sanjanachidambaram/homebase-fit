"""Red-flag check: plain code, no LLM. Runs on the user's own words (calendar notes, cardio logs) when saved.

If the text mentions pain/injury warning signs or describes the user's own injury, we log a safety_events row and
show a fixed, supportive message that points the user to a doctor or physical therapist. The words are still saved
(it's their log) and never sent to any model. Being deterministic makes it cheap, predictable, and fully testable.
It errs on the side of pointing to a professional. (It also guarded the Workout Basics Q&A until that feature was
removed, 2026-10-25.)

The term list is a placeholder for the PT/OB-GYN to review.
"""

import re

from app.db import connect

# For a calendar note that trips the check: the note is still saved (it's their log), and this shows inline.
NOTE_SUPPORT_MESSAGE = (
    "Your note is saved. It sounds like something hurt or didn't feel right, and that's worth taking seriously. "
    "Please stop any exercise that causes it and check in with a doctor or physical therapist before your next "
    "session. If it's severe or sudden, like chest pain, trouble breathing, or fainting, get medical help right away."
)

_CANT = r"(?:can'?t|cannot|can not|unable to)"
BODY = (r"(?:back|lower back|neck|knee|knees|shoulder|shoulders|hip|hips|ankle|ankles|wrist|wrists|elbow|elbows|"
        r"foot|feet|leg|legs|arm|arms|hand|hands|chest|stomach|belly|abdomen|pelvis|pelvic floor|hamstring|"
        r"calf|calves|groin|spine|joint|joints|head)")

# (label, pattern). Labels are what gets reported; patterns run on lowercased text.
RED_FLAGS: list[tuple[str, str]] = [
    ("sharp/severe pain", r"\b(?:sharp|stabbing|shooting|severe|sudden|intense|excruciating|radiating|burning|"
                          r"worsening|unbearable|constant)\s+(?:\w+\s+)?pain\b"),
    ("severe", r"\bsevere(?:ly)?\b"),
    ("numbness/tingling", r"\b(?:numb|numbness|tingl\w*|pins and needles|loss of (?:feeling|sensation))\b"),
    ("can't move / bear weight", rf"\b{_CANT}\s+(?:move|walk|stand|bear weight|put weight|straighten|bend|lift|"
                                 rf"raise|turn|grip|feel)\b"),
    ("chest pain / breathing", r"\b(?:chest (?:pain|tightness|pressure)|tight chest|short(?:ness)? of breath|"
                               rf"{_CANT} breathe|trouble breathing|difficulty breathing|heart (?:racing|pounding)|"
                               r"palpitations?|irregular heartbeat)\b"),
    ("dizzy/fainting", r"\b(?:dizzy|dizziness|light-?headed|faint(?:ed|ing)?|passed out|blacked out|black out)\b"),
    ("swelling/bruising", r"\b(?:swollen|swelling|bruis\w+|lump)\b"),
    ("pop/tear/break", r"\b(?:heard a pop|felt a pop|popping sound|torn|tore|tear in|ruptur\w+|broke my|"
                       r"broken (?:bone|arm|leg|wrist|ankle|foot|toe|finger|rib|hand)|fractur\w+|dislocat\w+|"
                       r"sprain\w*|strained)\b"),
    ("bleeding / pregnancy warning", r"\b(?:bleeding|blood in|(?:having|feeling|getting|started) contractions|leaking fluid)\b"),
    ("loss of control", r"\bloss of (?:bladder|bowel) control\b"),
    ("my injury", r"\bi\s+(?:think\s+i\s+)?(?:hurt|injured|tweaked|pulled|twisted|wrenched)\s+my\b"),
    ("my body part hurts", rf"\bmy\s+(?:\w+\s+)?{BODY}\s+(?:hurts?|is hurting|aches?|is aching|is sore|is swollen|"
                           rf"is killing me|gave out|gives out|locks?|clicks? and hurts)\b"),
    ("pain in my", rf"\b(?:pain|ache|aching|soreness|hurts?)\s+(?:in|on|around|behind)\s+my\b"),
    ("i have pain", r"\bi(?:'m| am)?\s+(?:have|having|got|get|getting|feel|feeling|felt|in)\s+(?:a\s+lot\s+of\s+|some\s+|"
                    r"bad\s+|really\s+bad\s+)?(?:pain|hurting)\b"),
    ("hurts when i", r"\b(?:it\s+)?hurts\s+(?:when|if|after|every time)\s+i\b"),
]
_COMPILED = [(label, re.compile(p)) for label, p in RED_FLAGS]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().replace("’", "'").replace("‘", "'"))


def red_flags_in(text: str) -> list[str]:
    """The red-flag labels found in the text (empty list if none)."""
    t = _normalize(text)
    return [label for label, rx in _COMPILED if rx.search(t)]


def log_safety_event(user_id: int | None, source: str, trigger_text: str,
                     action_taken: str = "redirected_to_professional") -> int:
    conn = connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO safety_events (user_id, source, trigger_text, action_taken) VALUES (?, ?, ?, ?)",
                (user_id, source, trigger_text[:500], action_taken))
        return cur.lastrowid
    finally:
        conn.close()

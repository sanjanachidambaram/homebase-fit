"""Export the exercise library to an Excel workbook for a manual content-review pass. Rerun it any time the data
changes; it overwrites the file.

Run from the project root (Windows):
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\export_exercise_review.py
or from backend/:
    .venv\\Scripts\\python.exe scripts\\export_exercise_review.py

Writes content/exercise_review_export.xlsx (gitignored: it's rebuilt from the database, so there's no point
versioning a binary copy). It reads the working database (backend/app/db/homebase.db, or HOMEBASE_DB_PATH) read-only.

Sheet "Exercises": one row per exercise, sorted by muscle group then name.
Sheet "Quiz Logic": every quiz question (wording and options read live from the database), the consent gate and the
calendar choice, with the column each is stored in, how the app uses it, and its safety / privacy notes. The script
stops with an error if a question or a quiz_profiles column isn't covered, so the sheet can't silently go stale.
"""

import json
import sys
from pathlib import Path

if __package__ in (None, ""):   # run as a script: make `import app...` work
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app import config
from app.db import connect_readonly

OUT = config.CONTENT_DIR / "exercise_review_export.xlsx"
HEADER_FILL = PatternFill("solid", fgColor="1F4E79")   # blue and white (AGENTS.md)
HEADER_FONT = Font(name="Times New Roman", bold=True, color="FFFFFF")
BODY_FONT = Font(name="Times New Roman")

EXERCISE_COLUMNS = [   # (header, width)
    ("name", 34), ("muscle_group", 13), ("equipment_needed", 20), ("difficulty", 12),
    ("injury draft areas", 26), ("injury reasoning (AI-drafted, pending PT review)", 90), ("source_dataset", 20),
    ("exercise_id", 30),
]


def _words(values: list[str]) -> str:
    return ", ".join(values)


def exercise_rows() -> list[list[str]]:
    conn = connect_readonly()
    try:
        rows = conn.execute(
            "SELECT id, name, muscle_group, equipment_needed, difficulty, injury_contraindications, injury_rationale, "
            "source_dataset, contraindication_status FROM exercises ORDER BY muscle_group, name COLLATE NOCASE").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        tags = json.loads(r["injury_contraindications"])
        rationale = json.loads(r["injury_rationale"] or "{}")
        reasoning = "\n".join(f"{t}: {rationale[t]['reasoning']}" for t in tags if t in rationale)
        if r["contraindication_status"] == "untagged":          # nobody has looked at it yet
            areas, reasoning = "(not checked yet)", "No injury cautions drafted yet."
        elif not tags:                                           # looked at, and judged to need none
            areas, reasoning = "none", "Drafted with no injury cautions (none judged plausible)."
        else:
            areas = _words(tags)
        out.append([r["name"], r["muscle_group"], _words(json.loads(r["equipment_needed"])), r["difficulty"],
                    areas, reasoning, r["source_dataset"], r["id"]])
    return out


# ---------------------------------------------------------------- sheet 2: Quiz Logic
#
# Traced from the code on 2026-10-24: content/quiz/quiz_questions.yaml, app/users.py (QUIZ_COLUMNS, save_quiz,
# reset_quiz), app/db/schema.sql (quiz_profiles), app/services/program_generator.py, app/agents/context.py and the
# agents, app/mcp_server/progress.py, app/services/workout_review.py, cardio_estimate.py, progress_marker.py,
# app/calendar.py, and the quiz page (frontend/src/pages/QuizPage.tsx). Wording and options come live from the
# database; check_quiz_coverage() refuses to write the sheet if a question or a quiz_profiles column has no row here.
AGENT_PROFILE = ("part of the PII-free agent profile (app/agents/context.py: goals, timeline, injury flags, age, "
                 "weight, height), which the Workout Builder's model can read through its get_user_profile tool")
QUIZ_LOGIC: dict[str, dict] = {
    "goals": {
        "db": "quiz_profiles.goals (JSON list)",
        "used": "Picks the training protocol: one goal_protocols row per goal at the user's experience level; with "
                "several goals they are blended using the gentler value wherever they differ (fewest sessions, "
                "shortest session, gentlest split, lower sets, lighter-load reps, longest rest). 'rehab' turns off "
                "progressive overload and makes the plan low-impact. The goal check (check_goal_achievement) adds a "
                "weigh-in trend check for weight_loss and a weight-lifted trend check for strength. Pound figures "
                "(Workout Reviewer, the calendar's progress marker) appear only with weight_loss.",
        "safety": "Not identifying. Sent to models: in the Program Architect's prompt, in the Coach's "
                  "check_goal_achievement tool result, and " + AGENT_PROFILE + ".",
    },
    "timeline": {
        "db": "quiz_profiles.timeline",
        "used": "The goal check's target sessions a week (4 weeks: 4; 8, 12 or 16 weeks: 3; no deadline: 2) and "
                "whether the timeline has ended. The Workout Reviewer's pound estimate covers this many weeks (4 for "
                "'no deadline').",
        "safety": "Not identifying. Sent to models: in the Coach's check_goal_achievement result, and "
                  + AGENT_PROFILE + ".",
    },
    "experience_level": {
        "db": "quiz_profiles.experience_level",
        "used": "Picks the goal_protocols row (goal x level) and caps exercise difficulty (beginner: beginner moves "
                "only; intermediate: up to intermediate; advanced: any). Beginners get low-impact plans.",
        "safety": "Sent to a model in the Program Architect's prompt. Not in the agent profile.",
    },
    "days_available": {
        "db": "quiz_profiles.days_available",
        "used": "Training days a week = the smallest of: this answer, the protocol's sessions per week, and 6 minus "
                "other-activity days (there's always at least one full rest day). The Workout Reviewer multiplies its "
                "per-session calorie range by this for the weekly range.",
        "safety": "Not sent as such; the Program Architect sees the resulting training days, and the Workout "
                  "Reviewer sees only the computed weekly range.",
    },
    "session_length": {
        "db": "quiz_profiles.session_length_minutes (stored as a number)",
        "used": "Each session's time budget: the shorter of this answer and the protocol's session length. The "
                "generator fits exercises into it.",
        "safety": "The Program Architect sees the session length in its prompt.",
    },
    "equipment": {
        "db": "quiz_profiles.equipment (JSON list)",
        "used": "Filters exercises in the generated plan. Mapped to library equipment (bodyweight -> none, dumbbells, "
                "resistance_band, mat, bench, kettlebells); bodyweight moves and a sturdy chair are always allowed; "
                "'A full gym' removes the equipment filter. 'Pull-up bar' maps to nothing yet (no library exercise is "
                "tagged with a bar), so it doesn't change the plan. Build Your Own uses the equipment picked on that "
                "page, not this answer.",
        "safety": "Not in the agent profile; never sent to a model (filters are applied in code).",
    },
    "other_activity_days": {
        "db": "quiz_profiles.other_activity_days (0 if left blank)",
        "used": "Lowers the planned training days so training plus other activity stays at 6 days a week or fewer "
                "(one full rest day), with a note on the plan saying so.",
        "safety": "Not sent to any model.",
    },
    "other_activity_notes": {
        "db": "quiz_profiles.other_activity_notes",
        "used": "Stored only. No code reads it after saving: it isn't shown back, doesn't change the plan, and isn't "
                "used anywhere else.",
        "safety": "The user's own words: never sent to any model (not in the agent profile, not read by any MCP "
                  "tool), the same rule as injury notes. Deleted with the account.",
    },
    "injuries": {
        "db": "quiz_profiles.injury_flags (JSON list; 'None' stores [])",
        "used": "Removes every exercise tagged unsafe for any flagged area (the SQL filter in search_exercises, used "
                "by the plan generator, the Workout Builder and the MCP tool) and forces checked_only (only exercises "
                "with drafted injury data). The plan lists what was left out and why. Also turns off progressive "
                "overload and makes the plan low-impact. 'None' clears the other choices.",
        "safety": "checked_only is set by code and the model can't loosen it. The flags (never the reasons) are "
                  + AGENT_PROFILE + "; the Program Architect sees only a yes/no 'low-impact injury-safe'.",
    },
    "injuries:free_text": {
        "label": "Anything else we should know? (free text under the injury question)",
        "format": "Free text, optional, up to 1,000 characters",
        "db": "quiz_profiles.injury_notes",
        "used": "Stored only. No code reads it after saving.",
        "safety": "Never sent to any model (on the excluded list in app/agents/context.py, with username, first name "
                  "and email). Deleted with the account.",
    },
    "pregnancy_status": {
        "db": "quiz_profiles.pregnancy_status, plus quiz_profiles.needs_clinical_review (computed by the database: "
              "1 for pregnant or postpartum)",
        "used": "Pregnant or postpartum: no plan is generated, the quiz sends them to /pregnancy-support, the "
                "calendar stays empty, Build Your Own and the calendar's day choices are blocked, and every AI route "
                "refuses (403, or a code-only reply for Ask the Basics after the red-flag check). They can still log "
                "cardio in their own words (no library picker), with no calorie estimates and no progress marker.",
        "safety": "Triggers needs_clinical_review, which blocks every AI feature, so no model is ever called for "
                  "them. Not in the agent profile; never sent to any model.",
    },
    "age": {
        "db": "quiz_profiles.age",
        "used": "Not used by any app logic (the plan generator doesn't read it).",
        "safety": "Sent to a model: " + AGENT_PROFILE + ".",
    },
    "weight": {
        "db": "quiz_profiles.weight (lb)",
        "used": "Calorie math done in code: the Workout Reviewer's estimate, cardio log estimates, calories on done "
                "calendar days and the progress marker (kcal = MET x kg x hours). The quiz page also uses it with "
                "goal weight and goal date for the gentle pace note.",
        "safety": "The calorie math never sends it to a model (the Workout Reviewer gets only computed ranges). It "
                  "does reach a model as " + AGENT_PROFILE + ". No calorie numbers at all while pregnant or "
                  "postpartum.",
    },
    "height": {
        "db": "quiz_profiles.height (total inches; asked in feet + inches)",
        "used": "Not used by any app logic.",
        "safety": "Sent to a model: " + AGENT_PROFILE + ".",
    },
    "goal_weight": {
        "db": "quiz_profiles.goal_weight (lb, optional)",
        "used": "Used only on the quiz page itself: with current weight and goal date, a gentle CDC-cited note appears "
                "if the goal means losing more than 2 lb a week (never a block). No backend logic reads it.",
        "safety": "Not in the agent profile; never sent to any model.",
    },
    "goal_date": {
        "db": "quiz_profiles.goal_date (YYYY-MM-DD, optional; must be in the future, within 5 years)",
        "used": "Only for the quiz page's pace note, with goal weight. No backend logic reads it.",
        "safety": "Not in the agent profile; never sent to any model.",
    },
}
# quiz_profiles columns that aren't quiz answers: the consent gate and what the app sets around the quiz.
QUIZ_EXTRA_ROWS = [
    {"label": "Medical disclaimer (checkbox before the health questions)",
     "format": "Required checkbox: \"I have read and understand this disclaimer...\"; the version shown is recorded",
     "db": "quiz_profiles.consent_accepted, consent_accepted_at (UTC), consent_version",
     "used": "The consent gate: the health questions stay hidden until it's ticked, the API refuses the quiz without "
             "it (422), and the database refuses a profile without it (CHECK). \"Reset my quiz\" deletes it, so a "
             "retake asks again.",
     "safety": "Records that the disclaimer was accepted and when. Never sent to a model."},
    {"label": "How do you want to populate your calendar? (asked right after the quiz; changeable in Settings)",
     "format": "Single-select: Use my quiz plan (generated, the default) | Let me review it first (review) | "
               "I'll build it myself (self)",
     "db": "quiz_profiles.calendar_mode",
     "used": "generated: the plan is laid out on the calendar. review: nothing is laid out until the user reviews "
             "the plan and optionally swaps exercises. self: days are open and filled with Build Your Own or cardio. "
             "Kept when the quiz is retaken.",
     "safety": "Blocked for pregnant / postpartum users (403). Not sent to a model."},
    {"label": "(set by the app) review-mode bookkeeping", "format": "Not asked",
     "db": "quiz_profiles.plan_reviewed, quiz_profiles.plan_swaps (JSON)",
     "used": "Whether a review-mode plan has been finalized, and the user's exercise swaps. Swaps are only accepted "
             "from the same injury-, equipment- and level-filtered pool. Both reset on every quiz save.",
     "safety": "Swaps can't get around the injury filter (checked when saved and again when the plan is built)."},
    {"label": "(set by the app) plan start", "format": "Not asked", "db": "quiz_profiles.plan_started_on",
     "used": "Week 1 of the plan for progressive overload (sets and reps step up every 2 weeks; flat for injury or "
             "rehab). Reset to today on every quiz save.",
     "safety": "Progression is off for anyone with an injury flag or a rehab goal."},
    {"label": "(set by the app) record keeping", "format": "Not asked",
     "db": "quiz_profiles.id, user_id, created_at, updated_at",
     "used": "created_at (the first quiz save) starts the goal check's clock: under 7 days it says it's too early to "
             "judge. user_id links the profile to the account.",
     "safety": "user_id is never sent to a model. The whole row is deleted with the account, or by \"Reset my quiz\"."},
]
QUIZ_COLUMNS = [("Quiz question", 42), ("Answer options / format", 48), ("Database field", 34),
                ("How it's used downstream", 70), ("Safety / privacy notes", 60)]


def _format(q, settings: dict) -> str:
    options = json.loads(q["options"])
    req = "required" if q["required"] else "optional"
    if q["question_type"] in ("multi_select", "single_select"):
        kind = "Multi-select" if q["question_type"] == "multi_select" else "Single-select"
        excl = f"; '{settings['exclusive']}' clears the others" if settings.get("exclusive") else ""
        return f"{kind} ({req}{excl}): " + " | ".join(f"{o['label']} ({o['value']})" for o in options)
    if q["question_type"] == "number":
        if settings.get("input") == "feet_inches":
            return f"Feet + inches ({req}), stored as total inches, {settings.get('min')} to {settings.get('max')} in"
        return f"Number ({req}), {settings.get('min')} to {settings.get('max')} {settings.get('unit', '')}".strip()
    if q["question_type"] == "date":
        return f"Date ({req})"
    return f"Free text ({req}), up to 500 characters"


def check_quiz_coverage(conn, questions) -> None:
    """Fail loudly if the quiz or the table changed and this sheet would be missing something."""
    ids = {q["id"] for q in questions}
    missing_q = ids - {k for k in QUIZ_LOGIC if ":" not in k}
    stale_q = {k for k in QUIZ_LOGIC if ":" not in k} - ids
    import re
    described = set(re.findall(r"[a-z_]+", " ".join(r["db"] for r in [*QUIZ_LOGIC.values(), *QUIZ_EXTRA_ROWS])))
    columns = [r[1] for r in conn.execute("PRAGMA table_xinfo(quiz_profiles)")]
    missing_c = [c for c in columns if c not in described]   # whole names only
    if missing_q or stale_q or missing_c:
        raise SystemExit(f"Quiz Logic sheet is out of date. Questions without a row: {sorted(missing_q)}; rows for "
                         f"questions that no longer exist: {sorted(stale_q)}; quiz_profiles columns not covered: "
                         f"{missing_c}. Update QUIZ_LOGIC in {Path(__file__).name}.")


def quiz_rows() -> list[list[str]]:
    conn = connect_readonly()
    try:
        questions = conn.execute("SELECT * FROM quiz_questions ORDER BY order_index").fetchall()
        check_quiz_coverage(conn, questions)
    finally:
        conn.close()
    rows = []
    for q in questions:
        settings = json.loads(q["settings"])
        logic = QUIZ_LOGIC[q["id"]]
        stage = " [health question: shown after the disclaimer]" if settings.get("health") else ""
        rows.append([q["prompt"] + stage, _format(q, settings), logic["db"], logic["used"], logic["safety"]])
        if settings.get("allow_free_text"):
            extra = QUIZ_LOGIC[f"{q['id']}:free_text"]
            rows.append([f"{settings.get('free_text_prompt') or extra['label']} (free text under \"{q['prompt']}\")",
                         extra["format"], extra["db"], extra["used"], extra["safety"]])
    rows += [[r["label"], r["format"], r["db"], r["used"], r["safety"]] for r in QUIZ_EXTRA_ROWS]
    return rows


def write_sheet(ws, columns: list[tuple[str, int]], rows: list[list], wrap: set[int] = frozenset()) -> None:
    ws.append([c[0] for c in columns])
    for cell in ws[1]:
        cell.font, cell.fill = HEADER_FONT, HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in rows:
        ws.append(row)
    for i, (_, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = BODY_FONT
            cell.alignment = Alignment(vertical="top", wrap_text=cell.column - 1 in wrap)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions


def build() -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Exercises"
    write_sheet(ws, EXERCISE_COLUMNS, exercise_rows(), wrap={5})
    write_sheet(wb.create_sheet("Quiz Logic"), QUIZ_COLUMNS, quiz_rows(), wrap={0, 1, 2, 3, 4})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path}")

"""Export the exercise library to an Excel workbook for a manual content-review pass. Rerun it any time the data
changes; it overwrites the file.

Run from the project root (Windows):
    backend\\.venv\\Scripts\\python.exe backend\\scripts\\export_exercise_review.py
or from backend/:
    .venv\\Scripts\\python.exe scripts\\export_exercise_review.py

Writes content/exercise_review_export.xlsx (gitignored: it's rebuilt from the database, so there's no point
versioning a binary copy). It reads the working database (backend/app/db/homebase.db, or HOMEBASE_DB_PATH) read-only.

Sheet "Exercises": one row per exercise, sorted by muscle group then name.
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
    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path}")

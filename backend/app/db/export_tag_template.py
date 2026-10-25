"""Write content/exercises/contraindication_tags_TEMPLATE.csv: one row per
exercise in the database (every source), for a PT to tag injuries.

Run from backend/ after seeding:
    .venv\\Scripts\\python.exe -m app.db.export_tag_template

This OVERWRITES the template. The PT should fill in a copy saved as
contraindication_tags.csv so a re-export never clobbers their work.

Columns neck / shoulder / upper_back / lower_back / wrist / hip / knee / ankle: Y = unsafe for that injury, N = OK,
blank = not reviewed. Drafted tags are pre-filled; imported exercises are blank.

Column rationale: WHY each Y is there, one "injury: reasoning" per line, pre-filled with the AI-drafted
reasoning (rationale_tier says ai_drafted) so the PT can confirm or correct it instead of starting from nothing.
"""

import csv
import json

from app.config import CONTENT_DIR
from app.db import connect_readonly
from app.safety_rules import INJURY_FLAGS

TEMPLATE = CONTENT_DIR / "exercises" / "contraindication_tags_TEMPLATE.csv"
INJURIES = INJURY_FLAGS   # app/safety_rules.py
COLUMNS = ("exercise_id", "name", "source_dataset", "muscle_group", "category", "equipment",
           "primary_muscles", "contraindication_status", *INJURIES, "rationale", "rationale_tier",
           "pt_notes", "reviewed_by")


def export() -> int:
    conn = connect_readonly()
    rows = conn.execute(
        "SELECT * FROM exercises ORDER BY source_dataset = 'free-exercise-db', muscle_group, name"
    ).fetchall()
    conn.close()
    # utf-8-sig so Excel opens it with the right encoding
    with TEMPLATE.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in rows:
            tags = set(json.loads(r["injury_contraindications"]))
            rationale = json.loads(r["injury_rationale"])
            tagged = r["contraindication_status"] != "untagged"
            w.writerow([
                r["id"], r["name"], r["source_dataset"], r["muscle_group"], r["category"] or "",
                ", ".join(json.loads(r["equipment_needed"])), ", ".join(json.loads(r["primary_muscles"])),
                r["contraindication_status"],
                *(("Y" if i in tags else "N") if tagged else "" for i in INJURIES),
                "\n".join(f"{i}: {rationale[i]['reasoning']}" for i in INJURIES if i in rationale),
                ", ".join(sorted({v["tier"] for v in rationale.values()})),
                "", "",
            ])
    return len(rows)


if __name__ == "__main__":
    print(f"Wrote {export()} exercises to {TEMPLATE.relative_to(CONTENT_DIR.parent).as_posix()}")

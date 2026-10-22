"""Build homebase_original.db from schema.sql + the files in content/,
then reset the working copy (homebase.db) from it.

Run from backend/ whenever you change anything in content/:
    .venv\\Scripts\\python.exe -m app.db.seed

This rebuilds from scratch, so it also wipes user data in the working copy.
Content problems (unknown exercise id, an exercise that's unsafe for the
program's injury_focus, missing fields) stop the build with a list of errors.
"""

import json
import os
import sqlite3
from pathlib import Path

import yaml

from app.config import CONTENT_DIR, DB_DIR, ORIGINAL_DB, PROJECT_ROOT
from app.db import connect, table_counts
from app.db.reset import reset

MUSCLE_GROUPS = ("legs", "arms", "back", "core", "full_body")
INJURY_TAGS = {"lower_back", "knee", "shoulder"}
DAYS = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}
MEDIA_EXTS = (".gif", ".mp4", ".webm", ".jpg", ".jpeg", ".png", ".webp")
DEFAULT_MEDIA_EXT = ".gif"


class ContentError(Exception):
    pass


def rel(path: Path) -> str:
    """Project-root-relative path with forward slashes (stored in the DB)."""
    return path.relative_to(PROJECT_ROOT).as_posix()


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def require(item: dict, fields: tuple[str, ...], where: str, errors: list[str]) -> bool:
    missing = [f for f in fields if item.get(f) in (None, "")]
    if missing:
        errors.append(f"{where}: missing {', '.join(missing)}")
    return not missing


# ---------------------------------------------------------------- loaders

def seed_quiz(conn: sqlite3.Connection, errors: list[str]) -> None:
    path = CONTENT_DIR / "quiz" / "quiz_questions.yaml"
    core = ("id", "prompt", "type", "options", "required")
    for i, q in enumerate(load_yaml(path).get("questions", [])):
        if not require(q, ("id", "prompt", "type"), f"{rel(path)} question {i + 1}", errors):
            continue
        settings = {k: v for k, v in q.items() if k not in core}
        conn.execute(
            "INSERT INTO quiz_questions (id, order_index, prompt, question_type, options, settings, required)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (q["id"], i, q["prompt"], q["type"], json.dumps(q.get("options", [])),
             json.dumps(settings), int(q.get("required", True))),
        )


def find_media(folder: Path, exercise_id: str) -> Path:
    """The demo file for an exercise if one exists, else the expected .gif path."""
    for ext in MEDIA_EXTS:
        candidate = folder / f"{exercise_id}{ext}"
        if candidate.exists():
            return candidate
    return folder / f"{exercise_id}{DEFAULT_MEDIA_EXT}"


def seed_exercises(conn: sqlite3.Connection, errors: list[str]) -> dict[str, set[str]]:
    """Returns {exercise_id: contraindications} for checking programs."""
    contraindications: dict[str, set[str]] = {}
    fields = ("id", "name", "difficulty", "instructions", "est_time_seconds")
    for group in MUSCLE_GROUPS:
        folder = CONTENT_DIR / "exercises" / group
        path = folder / "exercises.yaml"
        if not path.exists():
            continue
        for ex in load_yaml(path).get("exercises", []):
            where = f"{rel(path)} {ex.get('id', '?')}"
            if not require(ex, fields, where, errors):
                continue
            if ex["id"] in contraindications:
                errors.append(f"{where}: duplicate exercise id")
                continue
            contra = ex.get("injury_contraindications") or []
            unknown = set(contra) - INJURY_TAGS
            if unknown:
                errors.append(f"{where}: unknown injury tag(s) {sorted(unknown)}")
            contraindications[ex["id"]] = set(contra)
            conn.execute(
                "INSERT INTO exercises (id, name, muscle_group, equipment_needed, difficulty,"
                " injury_contraindications, demo_media_path, instructions, est_time_seconds)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ex["id"], ex["name"], group, json.dumps(ex.get("equipment_needed") or ["none"]),
                 ex["difficulty"], json.dumps(contra), rel(find_media(folder, ex["id"])),
                 ex["instructions"].strip(), int(ex["est_time_seconds"])),
            )
    return contraindications


def seed_programs(conn: sqlite3.Connection, contraindications: dict[str, set[str]], errors: list[str]) -> None:
    fields = ("name", "goal_tags", "description", "science_rationale", "created_by", "schedule")
    for path in sorted((CONTENT_DIR / "programs").glob("*.yaml")):
        p = load_yaml(path)
        if not require(p, fields, rel(path), errors):
            continue
        focus = set(p.get("injury_focus") or [])
        cur = conn.execute(
            "INSERT INTO program_templates (name, goal_tags, injury_focus, description,"
            " science_rationale, created_by, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (p["name"], json.dumps(p["goal_tags"]), json.dumps(sorted(focus)), p["description"].strip(),
             p["science_rationale"].strip(), p["created_by"], rel(path)),
        )
        program_id = cur.lastrowid
        for day, items in p["schedule"].items():
            day_num = DAYS.get(str(day).lower()[:3])
            if day_num is None:
                errors.append(f"{rel(path)}: unknown day '{day}' (use mon..sun)")
                continue
            for order, item in enumerate(items or []):
                where = f"{rel(path)} {day} #{order + 1}"
                ex_id = item.get("exercise")
                if ex_id not in contraindications:
                    errors.append(f"{where}: unknown exercise '{ex_id}'")
                    continue
                unsafe = contraindications[ex_id] & focus
                if unsafe:
                    errors.append(f"{where}: '{ex_id}' is contraindicated for {sorted(unsafe)}, "
                                  f"which this program's injury_focus covers")
                    continue
                conn.execute(
                    "INSERT INTO program_template_exercises (program_id, exercise_id, day_of_week,"
                    " sets, reps, order_index) VALUES (?, ?, ?, ?, ?, ?)",
                    (program_id, ex_id, day_num, int(item.get("sets", 1)), str(item.get("reps", "")), order),
                )


def split_front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        _, header, body = text.split("---", 2)
        return yaml.safe_load(header) or {}, body.strip()
    return {}, text.strip()


def seed_basics(conn: sqlite3.Connection, errors: list[str]) -> None:
    for path in sorted((CONTENT_DIR / "basics").glob("*.md")):
        meta, body = split_front_matter(path.read_text(encoding="utf-8"))
        if not require(meta, ("title", "category"), rel(path), errors):
            continue
        conn.execute(
            "INSERT INTO basics_articles (slug, title, category, content, media_path) VALUES (?, ?, ?, ?, ?)",
            (path.stem, meta["title"], meta["category"], body, meta.get("media_path")),
        )


# ---------------------------------------------------------------- build

def build_original() -> None:
    tmp = DB_DIR / "homebase_original.building.db"
    tmp.unlink(missing_ok=True)
    conn = connect(tmp)
    errors: list[str] = []
    ok = False
    try:
        conn.executescript((DB_DIR / "schema.sql").read_text(encoding="utf-8"))
        seed_quiz(conn, errors)
        contraindications = seed_exercises(conn, errors)
        seed_programs(conn, contraindications, errors)
        seed_basics(conn, errors)
        if errors:
            raise ContentError("\n".join(f"  - {e}" for e in errors))
        conn.commit()
        ok = True
    finally:
        conn.close()
        if not ok:
            tmp.unlink(missing_ok=True)
    os.replace(tmp, ORIGINAL_DB)


if __name__ == "__main__":
    try:
        build_original()
    except ContentError as e:
        raise SystemExit(f"Seed failed; {ORIGINAL_DB.name} was not changed:\n{e}")
    reset()
    conn = connect()
    counts = table_counts(conn)
    conn.close()
    print(f"Built {ORIGINAL_DB.name} and reset the working copy.")
    for table, n in counts.items():
        print(f"  {table:28} {n}")

"""Build homebase_original.db from schema.sql + the files in content/,
then reset the working copy (homebase.db) from it.

Run from backend/ whenever you change anything in content/:
    .venv\\Scripts\\python.exe -m app.db.seed

This rebuilds from scratch, so it also wipes user data in the working copy.
Content problems (unknown exercise id, an exercise that's unsafe for the
program's injury_focus, missing fields, unknown source) stop the build with
a list of errors.
"""

import json
import os
import sqlite3
from pathlib import Path

import yaml

from app.config import CONTENT_DIR, DB_DIR, ORIGINAL_DB, PROJECT_ROOT
from app.db import connect, table_counts
from app.db.reset import reset

MUSCLE_GROUPS = ("legs", "arms", "chest", "shoulders", "back", "core", "full_body")
INJURY_TAGS = {"lower_back", "knee", "shoulder"}
DAYS = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}
VIDEO_EXTS = (".mp4", ".webm")
MEDIA_EXTS = (".gif", *VIDEO_EXTS, ".jpg", ".jpeg", ".png", ".webp")
DEFAULT_MEDIA_EXT = ".gif"
DEFAULT_SOURCE = "placeholder-authored"   # the hand-authored drafts in content/

# ---- free-exercise-db mapping onto HomeBase Fit's categories
FEDB_SOURCE = "free-exercise-db"
FEDB_DIR = CONTENT_DIR / "exercises" / "source_free_exercise_db"
FEDB_MUSCLE_TO_GROUP = {
    "abdominals": "core",
    "lower back": "back", "middle back": "back", "lats": "back", "traps": "back", "neck": "back",
    "quadriceps": "legs", "hamstrings": "legs", "glutes": "legs", "calves": "legs",
    "adductors": "legs", "abductors": "legs",
    "biceps": "arms", "triceps": "arms", "forearms": "arms",
    "chest": "chest", "shoulders": "shoulders",
}
FEDB_FULL_BODY_CATEGORIES = {"cardio", "olympic weightlifting", "strongman"}
FEDB_EQUIPMENT = {
    None: "none", "body only": "none", "dumbbell": "dumbbells", "bands": "resistance_band",
    "kettlebells": "kettlebells", "barbell": "barbell", "machine": "machine", "cable": "cable",
    "foam roll": "foam_roller", "medicine ball": "medicine_ball", "exercise ball": "exercise_ball",
    "e-z curl bar": "ez_curl_bar", "other": "other",
}
FEDB_LEVEL = {"beginner": "beginner", "intermediate": "intermediate", "expert": "advanced"}
FEDB_EST_SECONDS = {"stretching": 30, "cardio": 60}   # everything else: 45


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


def review_fields(item: dict, where: str, errors: list[str]) -> tuple[str, str] | None:
    """Validate status + citations; returns (status, citations_json) or None.
    Citation integrity: content can't be marked pt_reviewed without at least
    one {claim, source} citation backing it."""
    status = item.get("status") or "placeholder"
    citations = item.get("citations") or []
    ok = True
    if status not in ("placeholder", "pt_reviewed"):
        errors.append(f"{where}: status must be placeholder or pt_reviewed, not '{status}'")
        ok = False
    if not isinstance(citations, list) or not all(
        isinstance(c, dict) and str(c.get("claim") or "").strip() and str(c.get("source") or "").strip()
        for c in citations
    ):
        errors.append(f"{where}: each citation needs a non-empty claim and source")
        ok = False
    elif status == "pt_reviewed" and not citations:
        errors.append(f"{where}: pt_reviewed content needs at least one citation")
        ok = False
    if not ok:
        return None
    clean = [{"claim": str(c["claim"]).strip(), "source": str(c["source"]).strip()} for c in citations]
    return status, json.dumps(clean)


def check_source(source_id: str, sources: set[str], where: str, errors: list[str]) -> bool:
    if source_id not in sources:
        errors.append(f"{where}: source '{source_id}' is not in content/sources.yaml")
        return False
    return True


# ---------------------------------------------------------------- loaders

def seed_sources(conn: sqlite3.Connection, errors: list[str]) -> set[str]:
    path = CONTENT_DIR / "sources.yaml"
    ids: set[str] = set()
    for i, s in enumerate(load_yaml(path).get("sources", [])):
        if not require(s, ("id", "name", "license", "used_for", "status"), f"{rel(path)} source {i + 1}", errors):
            continue
        ids.add(s["id"])
        conn.execute(
            "INSERT INTO sources (id, order_index, name, url, license, used_for, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (s["id"], i, s["name"], s.get("url") or None, s["license"], s["used_for"], s["status"]),
        )
    return ids


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


def media_type_for(path: str | None) -> str | None:
    """'image' | 'gif' | 'video' from a media path's extension (None if there's no path)."""
    if not path:
        return None
    ext = Path(path).suffix.lower()
    if ext == ".gif":
        return "gif"
    return "video" if ext in VIDEO_EXTS else "image"


def insert_exercise(conn: sqlite3.Connection, **ex) -> None:
    ex["media_type"] = media_type_for(ex["demo_media_path"])
    ex.setdefault("status", "placeholder")
    ex.setdefault("citations", "[]")
    conn.execute(
        "INSERT INTO exercises (id, name, muscle_group, equipment_needed, difficulty,"
        " injury_contraindications, contraindication_status, demo_media_path, media_type, instructions,"
        " est_time_seconds, category, primary_muscles, secondary_muscles, source_dataset, status, citations)"
        " VALUES (:id, :name, :muscle_group, :equipment_needed, :difficulty,"
        " :injury_contraindications, :contraindication_status, :demo_media_path, :media_type, :instructions,"
        " :est_time_seconds, :category, :primary_muscles, :secondary_muscles, :source_dataset, :status, :citations)",
        ex,
    )


def seed_authored_exercises(conn: sqlite3.Connection, errors: list[str]) -> dict[str, set[str]]:
    """Hand-authored drafts in content/exercises/<group>/exercises.yaml.
    Returns {exercise_id: contraindications} for checking programs."""
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
            review = review_fields(ex, where, errors)   # optional status + citations in the yaml
            if review is None:
                continue
            contraindications[ex["id"]] = set(contra)
            insert_exercise(
                conn, id=ex["id"], name=ex["name"], muscle_group=group,
                equipment_needed=json.dumps(ex.get("equipment_needed") or ["none"]),
                difficulty=ex["difficulty"], injury_contraindications=json.dumps(contra),
                contraindication_status="draft", demo_media_path=rel(find_media(folder, ex["id"])),
                instructions=ex["instructions"].strip(), est_time_seconds=int(ex["est_time_seconds"]),
                category=None, primary_muscles="[]", secondary_muscles="[]", source_dataset=DEFAULT_SOURCE,
                status=review[0], citations=review[1],
            )
    return contraindications


def fedb_muscle_group(ex: dict) -> str:
    if ex.get("category") in FEDB_FULL_BODY_CATEGORIES:
        return "full_body"
    groups = {FEDB_MUSCLE_TO_GROUP.get(m) for m in ex.get("primaryMuscles", [])} - {None}
    if len(groups) == 1:
        return groups.pop()
    return "full_body"   # several (or no) primary groups


def seed_free_exercise_db(conn: sqlite3.Connection, taken_ids: set[str], errors: list[str]) -> None:
    """Imported library from content/exercises/source_free_exercise_db/ (see ATTRIBUTION.md).
    No injury info in the dataset, so every row starts 'untagged'."""
    path = FEDB_DIR / "exercises.json"
    if not path.exists():
        return
    for ex in json.loads(path.read_text(encoding="utf-8")):
        where = f"{rel(path)} {ex.get('id', '?')}"
        if not require(ex, ("id", "name", "level", "instructions"), where, errors):
            continue
        if ex["id"] in taken_ids:
            errors.append(f"{where}: id already used by another exercise")
            continue
        if ex.get("equipment") not in FEDB_EQUIPMENT or ex["level"] not in FEDB_LEVEL:
            errors.append(f"{where}: unmapped equipment '{ex.get('equipment')}' or level '{ex['level']}'")
            continue
        taken_ids.add(ex["id"])
        image = FEDB_DIR / "images" / ex["images"][0] if ex.get("images") else None
        insert_exercise(
            conn, id=ex["id"], name=ex["name"], muscle_group=fedb_muscle_group(ex),
            equipment_needed=json.dumps([FEDB_EQUIPMENT[ex.get("equipment")]]),
            difficulty=FEDB_LEVEL[ex["level"]], injury_contraindications="[]",
            contraindication_status="untagged", demo_media_path=rel(image) if image else None,
            instructions="\n".join(step.strip() for step in ex["instructions"]),
            est_time_seconds=FEDB_EST_SECONDS.get(ex.get("category"), 45), category=ex.get("category"),
            primary_muscles=json.dumps(ex.get("primaryMuscles", [])),
            secondary_muscles=json.dumps(ex.get("secondaryMuscles", [])), source_dataset=FEDB_SOURCE,
        )


def seed_programs(conn: sqlite3.Connection, contraindications: dict[str, set[str]],
                  sources: set[str], errors: list[str]) -> None:
    """Programs may only use hand-authored exercises (the ones with drafted injury tags)."""
    fields = ("name", "goal_tags", "description", "science_rationale", "created_by", "schedule")
    for path in sorted((CONTENT_DIR / "programs").glob("*.yaml")):
        p = load_yaml(path)
        if not require(p, fields, rel(path), errors):
            continue
        source = p.get("source") or DEFAULT_SOURCE
        if not check_source(source, sources, rel(path), errors):
            continue
        review = review_fields(p, rel(path), errors)
        if review is None:
            continue
        focus = set(p.get("injury_focus") or [])
        cur = conn.execute(
            "INSERT INTO program_templates (name, goal_tags, injury_focus, description, science_rationale,"
            " created_by, source_id, source_file, status, citations) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["name"], json.dumps(p["goal_tags"]), json.dumps(sorted(focus)), p["description"].strip(),
             p["science_rationale"].strip(), p["created_by"], source, rel(path), *review),
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


def seed_basics(conn: sqlite3.Connection, sources: set[str], errors: list[str]) -> None:
    for path in sorted((CONTENT_DIR / "basics").glob("*.md")):
        meta, body = split_front_matter(path.read_text(encoding="utf-8"))
        if not require(meta, ("title", "category"), rel(path), errors):
            continue
        source = meta.get("source") or DEFAULT_SOURCE
        if not check_source(source, sources, rel(path), errors):
            continue
        review = review_fields(meta, rel(path), errors)
        if review is None:
            continue
        conn.execute(
            "INSERT INTO basics_articles (slug, title, category, content, media_path, source_id, status, citations)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (path.stem, meta["title"], meta["category"], body, meta.get("media_path"), source, *review),
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
        sources = seed_sources(conn, errors)
        seed_quiz(conn, errors)
        contraindications = seed_authored_exercises(conn, errors)
        seed_free_exercise_db(conn, set(contraindications), errors)
        seed_programs(conn, contraindications, sources, errors)
        seed_basics(conn, sources, errors)
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

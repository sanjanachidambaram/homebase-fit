"""Load the content in content/ (sources, quiz questions, exercises, goal protocols) into the Postgres content tables.

Run from backend/ whenever you change anything in content/ (the app also does it by itself at startup when the
content files changed: app/db/__init__.py ensure_database):
    .venv\\Scripts\\python.exe -m app.db.seed                 migrate the schema, reload the content; KEEP every account
    .venv\\Scripts\\python.exe -m app.db.seed --wipe-users    the same, then wipe all user data (a clean demo database)

Only the content tables are replaced, inside one transaction: accounts, quiz answers, logs, calendar and favorites are
never touched (a favorite or log pointing at an exercise that was removed from content is dropped / unlinked).
Content problems (missing fields, a bad goal protocol, an unknown source or injury tag, an injury tag with no
rationale) stop the load with a list of errors, and the database is left exactly as it was.
(Until 2026-10-25 this built a SQLite file, homebase_original.db; the loaders below are unchanged.)
"""

import hashlib
import json
import sys
from pathlib import Path

import yaml

from app.config import CONTENT_DIR, PROJECT_ROOT
from app.db import META_KEY, connect, table_counts, to_pg, _params
from app.safety_rules import INJURY_FLAGS, RATIONALE_CITATION_LIKE, RATIONALE_PENDING_SOURCE, RATIONALE_TIERS

MUSCLE_GROUPS = ("legs", "arms", "chest", "shoulders", "back", "core", "full_body")
FORCES = {"push", "pull", "static", None}   # movement direction; None = no single direction
INJURY_TAGS = set(INJURY_FLAGS)   # app/safety_rules.py
GOALS = ("stronger", "lose_weight", "feel_good")
EXPERIENCE = ("beginner", "intermediate", "advanced")
VIDEO_EXTS = (".mp4", ".webm")
MEDIA_EXTS = (".gif", *VIDEO_EXTS, ".jpg", ".jpeg", ".png", ".webp")
DEFAULT_MEDIA_EXT = ".gif"
DEFAULT_SOURCE = "placeholder-authored"   # the hand-authored drafts in content/

# ---- free-exercise-db mapping onto Bee Fit's categories
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

def seed_sources(conn, errors: list[str]) -> set[str]:
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


def seed_quiz(conn, errors: list[str]) -> None:
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


def insert_exercise(conn, **ex) -> None:
    ex["media_type"] = media_type_for(ex["demo_media_path"])
    ex.setdefault("status", "placeholder")
    ex.setdefault("citations", "[]")
    ex.setdefault("injury_rationale", "{}")
    ex.setdefault("force", None)
    conn.execute(
        "INSERT INTO exercises (id, name, muscle_group, equipment_needed, difficulty,"
        " injury_contraindications, contraindication_status, injury_rationale, force, demo_media_path, media_type, instructions,"
        " est_time_seconds, category, primary_muscles, secondary_muscles, source_dataset, status, citations)"
        " VALUES (:id, :name, :muscle_group, :equipment_needed, :difficulty,"
        " :injury_contraindications, :contraindication_status, :injury_rationale, :force, :demo_media_path, :media_type, :instructions,"
        " :est_time_seconds, :category, :primary_muscles, :secondary_muscles, :source_dataset, :status, :citations)",
        ex,
    )


def injury_rationale(ex: dict, contra: list[str], where: str, errors: list[str]) -> dict:
    """Every injury tag needs a {reasoning, tier, source} entry, and nothing else may have one.
    pt_reviewed must name a real reviewer in source, not the pending placeholder."""
    rationale = ex.get("injury_rationale") or {}
    if not isinstance(rationale, dict):
        errors.append(f"{where}: injury_rationale must be a mapping of injury -> {{reasoning, tier, source}}")
        return {}
    if set(rationale) != set(contra):
        errors.append(f"{where}: injury_rationale must have exactly one entry per injury tag "
                      f"(tags {sorted(contra)}, rationale {sorted(rationale)})")
    for injury, r in rationale.items():
        if not isinstance(r, dict) or set(r) != {"reasoning", "tier", "source"}:
            errors.append(f"{where} {injury}: rationale needs exactly reasoning, tier, source")
            continue
        if not str(r["reasoning"]).strip() or not str(r["source"]).strip():
            errors.append(f"{where} {injury}: reasoning and source can't be empty")
        if r["tier"] not in RATIONALE_TIERS:
            errors.append(f"{where} {injury}: tier must be one of {list(RATIONALE_TIERS)}")
        if r["tier"] == "pt_reviewed" and r["source"] == RATIONALE_PENDING_SOURCE:
            errors.append(f"{where} {injury}: pt_reviewed needs the reviewing PT's name and credentials as source")
        if r["tier"] == "ai_drafted" and r["source"] != RATIONALE_PENDING_SOURCE:
            errors.append(f"{where} {injury}: ai_drafted rationale must have source '{RATIONALE_PENDING_SOURCE}'")
        if RATIONALE_CITATION_LIKE.search(str(r["reasoning"])):
            errors.append(f"{where} {injury}: reasoning must not look like a citation (years, journals, 'research', "
                          "'studies show')")
    return {i: {k: str(rationale[i][k]).strip() for k in ("reasoning", "tier", "source")}
            for i in contra if isinstance(rationale.get(i), dict) and set(rationale[i]) == {"reasoning", "tier", "source"}}


def seed_authored_exercises(conn, errors: list[str]) -> dict[str, set[str]]:
    """Hand-authored drafts in content/exercises/<group>/exercises.yaml.
    Returns {exercise_id: contraindications}."""
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
            rationale = injury_rationale(ex, contra, where, errors)
            if ex.get("force") not in FORCES:
                errors.append(f"{where}: force must be push, pull or static (or left out), not {ex.get('force')!r}")
            review = review_fields(ex, where, errors)   # optional status + citations in the yaml
            if review is None:
                continue
            contraindications[ex["id"]] = set(contra)
            insert_exercise(
                conn, id=ex["id"], name=ex["name"], muscle_group=group,
                equipment_needed=json.dumps(ex.get("equipment_needed") or ["none"]),
                difficulty=ex["difficulty"], injury_contraindications=json.dumps(contra),
                injury_rationale=json.dumps(rationale), force=ex.get("force"),
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


def seed_free_exercise_db(conn, taken_ids: set[str], errors: list[str]) -> None:
    """Imported library from content/exercises/source_free_exercise_db/ (see ATTRIBUTION.md).
    The dataset has no injury info. Exercises with an entry in injury_tags_ai_drafted.json (the one-time AI drafting,
    app/db/draft_injury_tags.py) get those drafted tags and reasons, status 'draft', validated exactly like the
    hand-authored ones; any without one stay 'untagged' (and out of injured users' plans)."""
    path = FEDB_DIR / "exercises.json"
    if not path.exists():
        return
    drafts_path = FEDB_DIR / "injury_tags_ai_drafted.json"
    drafts = json.loads(drafts_path.read_text(encoding="utf-8"))["drafts"] if drafts_path.exists() else {}
    for ex in json.loads(path.read_text(encoding="utf-8")):
        where = f"{rel(path)} {ex.get('id', '?')}"
        if not require(ex, ("id", "name", "level", "instructions"), where, errors):
            continue
        if ex["id"] in taken_ids:
            errors.append(f"{where}: id already used by another exercise")
            continue
        if ex.get("equipment") not in FEDB_EQUIPMENT or ex["level"] not in FEDB_LEVEL or ex.get("force") not in FORCES:
            errors.append(f"{where}: unmapped equipment '{ex.get('equipment')}', level '{ex['level']}' "
                          f"or force '{ex.get('force')}'")
            continue
        taken_ids.add(ex["id"])
        image = FEDB_DIR / "images" / ex["images"][0] if ex.get("images") else None
        contra, rationale, status = [], {}, "untagged"
        if ex["id"] in drafts:
            d, dwhere = drafts[ex["id"]], f"{rel(drafts_path)} {ex['id']}"
            contra = d.get("injury_contraindications") or []
            if set(contra) - INJURY_TAGS:
                errors.append(f"{dwhere}: unknown injury tag(s) {sorted(set(contra) - INJURY_TAGS)}")
            if any(r.get("tier") != "ai_drafted" for r in (d.get("injury_rationale") or {}).values()):
                errors.append(f"{dwhere}: generated drafts are always tier ai_drafted")
            rationale, status = injury_rationale(d, contra, dwhere, errors), "draft"
        insert_exercise(
            conn, id=ex["id"], name=ex["name"], muscle_group=fedb_muscle_group(ex),
            equipment_needed=json.dumps([FEDB_EQUIPMENT[ex.get("equipment")]]),
            difficulty=FEDB_LEVEL[ex["level"]], injury_contraindications=json.dumps(contra), force=ex.get("force"),
            contraindication_status=status, injury_rationale=json.dumps(rationale),
            demo_media_path=rel(image) if image else None,
            instructions="\n".join(step.strip() for step in ex["instructions"]),
            est_time_seconds=FEDB_EST_SECONDS.get(ex.get("category"), 45), category=ex.get("category"),
            primary_muscles=json.dumps(ex.get("primaryMuscles", [])),
            secondary_muscles=json.dumps(ex.get("secondaryMuscles", [])), source_dataset=FEDB_SOURCE,
        )


def parse_range(text: str) -> tuple[int, int] | None:
    """"2-3" -> (2, 3); "3" -> (3, 3); anything else -> None."""
    parts = str(text).replace(" ", "").split("-")
    if not 1 <= len(parts) <= 2 or not all(p.isdigit() for p in parts):
        return None
    lo, hi = int(parts[0]), int(parts[-1])
    return (lo, hi) if 0 < lo <= hi else None


def seed_goal_protocols(conn, sources: set[str], errors: list[str]) -> None:
    """content/protocols/goal_protocols.yaml: exactly one row per goal x experience level."""
    path = CONTENT_DIR / "protocols" / "goal_protocols.yaml"
    fields = ("goal", "experience_level", "session_length_minutes", "sets_range", "reps_range", "rest_seconds",
              "progression_note")
    seen: set[tuple[str, str]] = set()
    for i, p in enumerate(load_yaml(path).get("protocols", [])):
        where = f"{rel(path)} row {i + 1} ({p.get('goal')}/{p.get('experience_level')})"
        if not require(p, fields, where, errors):
            continue
        key = (p["goal"], p["experience_level"])
        problems = []
        if p["goal"] not in GOALS:
            problems.append(f"goal must be one of {GOALS}")
        if p["experience_level"] not in EXPERIENCE:
            problems.append(f"experience_level must be one of {EXPERIENCE}")
        if parse_range(p["sets_range"]) is None or parse_range(p["reps_range"]) is None:
            problems.append('sets_range and reps_range must look like "2-3" or "10"')
        if not 15 <= int(p["session_length_minutes"]) <= 60:
            problems.append("session_length_minutes must be 15-60")
        if key in seen:
            problems.append("duplicate goal + experience_level")
        if problems:
            errors.extend(f"{where}: {x}" for x in problems)
            continue
        source = p.get("source") or DEFAULT_SOURCE
        review = review_fields(p, where, errors)
        if review is None or not check_source(source, sources, where, errors):
            continue
        seen.add(key)
        conn.execute(
            "INSERT INTO goal_protocols (goal, experience_level, session_length_minutes, sets_range, reps_range, "
            "rest_seconds, progression_note, reference_notes, source_id, status, citations) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (p["goal"], p["experience_level"], int(p["session_length_minutes"]),
             str(p["sets_range"]), str(p["reps_range"]), int(p["rest_seconds"]),
             p["progression_note"].strip(), (p.get("reference_notes") or "").strip() or None, source, *review))
    missing = [f"{g}/{e}" for g in GOALS for e in EXPERIENCE if (g, e) not in seen]
    if missing and not any(rel(path) in e for e in errors):
        errors.append(f"{rel(path)}: missing protocols for {missing}")


# ---------------------------------------------------------------- build

CONTENT_TABLES = ("goal_protocols", "exercises", "quiz_questions", "sources")   # children first
_TEXT_FILES = {".yaml", ".yml", ".json", ".md", ".csv"}


def content_fingerprint() -> str:
    """Changes whenever a deploy ships different content: every file under content/ (text files by their bytes, media
    by name and size, since a demo file appearing changes an exercise's media path), plus this loader's own code."""
    h = hashlib.sha256(Path(__file__).read_bytes())
    for f in sorted(p for p in CONTENT_DIR.rglob("*") if p.is_file()):
        h.update(f.relative_to(CONTENT_DIR).as_posix().encode())
        h.update(f.read_bytes() if f.suffix.lower() in _TEXT_FILES else str(f.stat().st_size).encode())
    return h.hexdigest()


class _Loader:
    """The loaders call conn.execute(sql, params) once per row; this sends those into a psycopg pipeline (no wait
    for each reply), so loading ~900 exercises over the network to Neon takes seconds, not minutes."""

    def __init__(self, raw):
        self._cur = raw.cursor()

    def execute(self, sql, params=None):
        self._cur.execute(to_pg(sql), _params(params))


def seed_content() -> dict[str, int]:
    """Replace the content tables from content/ in one transaction. Raises ContentError (nothing changed) on bad
    content. Returns the new row counts of the content tables."""
    errors: list[str] = []
    conn = connect()
    try:
        raw = conn.raw
        with raw.transaction():
            raw.execute("SET CONSTRAINTS ALL DEFERRED")   # user rows point at exercises; checked again at commit
            for table in CONTENT_TABLES:
                raw.execute(f"DELETE FROM {table}")
            loader = _Loader(raw)
            with raw.pipeline():
                sources = seed_sources(loader, errors)
                seed_quiz(loader, errors)
                contraindications = seed_authored_exercises(loader, errors)
                seed_free_exercise_db(loader, set(contraindications), errors)
                seed_goal_protocols(loader, sources, errors)
            if errors:
                raise ContentError("\n".join(f"  - {e}" for e in errors))   # rolls the whole thing back
            # User data that pointed at an exercise no longer in the library: drop the favorite, unlink the log.
            raw.execute("DELETE FROM exercise_favorites WHERE exercise_id NOT IN (SELECT id FROM exercises)")
            raw.execute("UPDATE workout_logs SET exercise_id = NULL "
                        "WHERE exercise_id IS NOT NULL AND exercise_id NOT IN (SELECT id FROM exercises)")
            raw.execute("UPDATE cardio_logs SET activity = COALESCE(activity, 'cardio'), exercise_id = NULL "
                        "WHERE exercise_id IS NOT NULL AND exercise_id NOT IN (SELECT id FROM exercises)")
            raw.execute("INSERT INTO app_meta (key, value) VALUES (%s, %s) "
                        "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (META_KEY, content_fingerprint()))
        counts = table_counts(conn)
    finally:
        conn.close()
    return {t: counts[t] for t in CONTENT_TABLES}


def main(argv: list[str]) -> dict[str, int]:
    """Migrate the schema, reload the content (keeping accounts), and with --wipe-users wipe all user data. Returns
    every table's row count afterwards."""
    from app.db.migrate import upgrade_to_head
    from app.db.reset import reset
    upgrade_to_head()
    try:
        seed_content()
    except ContentError as e:
        raise SystemExit(f"Seed failed; the database was not changed:\n{e}")
    if "--wipe-users" in argv:
        reset()
        print("Loaded the content and wiped all user data.")
    else:
        print("Loaded the content, keeping every account.")
    conn = connect()
    try:
        counts = table_counts(conn)
    finally:
        conn.close()
    for table, n in counts.items():
        print(f"  {table:28} {n}")
    return counts


if __name__ == "__main__":
    main(sys.argv[1:])

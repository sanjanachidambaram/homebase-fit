"""FastAPI entry point for HomeBase Fit.

Run locally from backend/ (no auto-reload, so edits never spawn extra servers):
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
"""

import json
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import CONTENT_DIR, MODEL_NAME, PROJECT_ROOT, WORKING_DB, is_production, llm_provider
from app.db import connect, ensure_working_db, table_counts

MuscleGroup = Literal["legs", "arms", "back", "core", "full_body"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_working_db()
    yield


app = FastAPI(title="HomeBase Fit API", lifespan=lifespan)

# Vite dev server; the hosted origin gets added at deploy time.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Demo images etc. DB media paths are project-relative ("content/..."), so the URL is "/" + path.
app.mount("/content", StaticFiles(directory=CONTENT_DIR), name="content")


def media_url(path: str | None) -> str | None:
    """URL for a media file, or None if the file isn't there yet."""
    return f"/{path}" if path and (PROJECT_ROOT / path).is_file() else None


@app.get("/api/health")
def health() -> dict:
    # Reports only whether a key is configured, never its value.
    return {"status": "ok", "model": MODEL_NAME, "llm_provider": llm_provider()}


@app.get("/api/exercises")
def list_exercises(
    muscle_group: MuscleGroup | None = None,
    source: str | None = Query(None, description="source_dataset id, e.g. free-exercise-db"),
) -> list[dict]:
    sql, args = "SELECT * FROM exercises WHERE 1 = 1", []
    if muscle_group:
        sql += " AND muscle_group = ?"
        args.append(muscle_group)
    if source:
        sql += " AND source_dataset = ?"
        args.append(source)
    sql += " ORDER BY source_dataset = 'free-exercise-db', name"
    conn = connect()
    try:
        rows = conn.execute(sql, args).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "muscle_group": r["muscle_group"],
            "equipment_needed": json.loads(r["equipment_needed"]),
            "difficulty": r["difficulty"],
            "category": r["category"],
            "primary_muscles": json.loads(r["primary_muscles"]),
            "injury_contraindications": json.loads(r["injury_contraindications"]),
            "contraindication_status": r["contraindication_status"],
            "est_time_seconds": r["est_time_seconds"],
            "instructions": r["instructions"],
            "demo_image_url": media_url(r["demo_media_path"]),
            "source_dataset": r["source_dataset"],
        }
        for r in rows
    ]


@app.get("/api/sources")
def list_sources() -> list[dict]:
    """The source registry (content/sources.yaml): where every piece of content comes from."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, name, url, license, used_for, status FROM sources ORDER BY order_index"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


@app.get("/api/debug/tables")
def debug_tables() -> dict:
    """Dev-only: row counts per table in the working database."""
    if is_production():
        raise HTTPException(404)
    conn = connect()
    try:
        return {"database": WORKING_DB.name, "tables": table_counts(conn)}
    finally:
        conn.close()

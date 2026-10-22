"""FastAPI entry point for HomeBase Fit.

Run locally from backend/ (no auto-reload, so edits never spawn extra servers):
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
"""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import config
from app.config import CONTENT_DIR, MODEL_NAME, is_production, llm_provider
from app.content import media_url, review_info
from app.db import connect, ensure_working_db, table_counts
from app.agent_routes import router as agent_router
from app.exercises import router as exercises_router
from app.users import router as users_router


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

app.include_router(users_router)
app.include_router(exercises_router)
app.include_router(agent_router)


@app.get("/api/health")
def health() -> dict:
    # Reports only whether a key is configured, never its value.
    return {"status": "ok", "model": MODEL_NAME, "llm_provider": llm_provider()}


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


@app.get("/api/programs")
def list_programs() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM program_templates ORDER BY name").fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "goal_tags": json.loads(r["goal_tags"]),
            "injury_focus": json.loads(r["injury_focus"]),
            "description": r["description"],
            "science_rationale": r["science_rationale"],
            **review_info(r),
            "source_id": r["source_id"],
        }
        for r in rows
    ]


@app.get("/api/basics")
def list_basics() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM basics_articles ORDER BY title").fetchall()
    finally:
        conn.close()
    return [
        {
            "slug": r["slug"],
            "title": r["title"],
            "category": r["category"],
            "content": r["content"],
            "media_url": media_url(r["media_path"]),
            **review_info(r),
            "source_id": r["source_id"],
        }
        for r in rows
    ]


@app.get("/api/debug/tables")
def debug_tables() -> dict:
    """Dev-only: row counts per table in the working database."""
    if is_production():
        raise HTTPException(404)
    conn = connect()
    try:
        return {"database": config.WORKING_DB.name, "tables": table_counts(conn)}
    finally:
        conn.close()

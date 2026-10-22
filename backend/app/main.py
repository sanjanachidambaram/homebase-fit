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
from app.calendar import router as calendar_router
from app.exercises import router as exercises_router
from app.services.program_generator import worked_example
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
app.include_router(calendar_router)


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


@app.get("/api/data-summary")
def data_summary() -> dict:
    """Live counts for the About page's "About the Data" section, so its numbers can never go stale:
    where the exercises come from, how many have any injury-safety review, and how much of the content
    is still placeholder vs reviewed or cited."""
    conn = connect()
    try:
        one = lambda sql: conn.execute(sql).fetchone()[0]   # noqa: E731
        by_source = conn.execute(
            "SELECT s.id, s.name, s.url, s.license, COUNT(e.id) AS count FROM exercises e "
            "JOIN sources s ON s.id = e.source_dataset GROUP BY s.id ORDER BY count DESC").fetchall()
        summary = {
            "exercises": {
                "total": one("SELECT COUNT(*) FROM exercises"),
                "by_source": [dict(r) for r in by_source],
                # "checked" = someone looked at it for injuries (draft or PT-reviewed), even if it got no caution
                "injury_checked": one("SELECT COUNT(*) FROM exercises WHERE contraindication_status <> 'untagged'"),
                "injury_unchecked": one("SELECT COUNT(*) FROM exercises WHERE contraindication_status = 'untagged'"),
                "injury_pt_reviewed": one("SELECT COUNT(*) FROM exercises WHERE contraindication_status = 'pt_reviewed'"),
                "with_cautions": one("SELECT COUNT(*) FROM exercises WHERE injury_contraindications <> '[]'"),
                "cautions": one("SELECT COUNT(*) FROM exercises e, json_each(e.injury_contraindications)"),
                "reasons_ai_drafted": one("SELECT COUNT(*) FROM exercises e, json_each(e.injury_rationale) r "
                                          "WHERE json_extract(r.value, '$.tier') = 'ai_drafted'"),
                "reasons_pt_reviewed": one("SELECT COUNT(*) FROM exercises e, json_each(e.injury_rationale) r "
                                           "WHERE json_extract(r.value, '$.tier') = 'pt_reviewed'"),
            },
            "protocols": {
                "total": one("SELECT COUNT(*) FROM goal_protocols"),
                "placeholder": one("SELECT COUNT(*) FROM goal_protocols WHERE status = 'placeholder'"),
                "with_citations": one("SELECT COUNT(*) FROM goal_protocols WHERE citations <> '[]'"),
            },
            "basics_articles": {
                "total": one("SELECT COUNT(*) FROM basics_articles"),
                "placeholder": one("SELECT COUNT(*) FROM basics_articles WHERE status = 'placeholder'"),
            },
        }
    finally:
        conn.close()
    return summary


@app.get("/api/plan/example")
def plan_example() -> dict:
    """Public: the worked example on the "How We Build Your Plan" page. A live run of the real generator
    for a fixed profile (no user data, no AI), so the example always matches the current algorithm."""
    return worked_example().model_dump()


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

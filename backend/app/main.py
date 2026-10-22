"""FastAPI entry point for HomeBase Fit.

Run locally from backend/ (no auto-reload, so edits never spawn extra servers):
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import MODEL_NAME, WORKING_DB, is_production, llm_provider
from app.db import connect, ensure_working_db, table_counts


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


@app.get("/api/health")
def health() -> dict:
    # Reports only whether a key is configured, never its value.
    return {"status": "ok", "model": MODEL_NAME, "llm_provider": llm_provider()}


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

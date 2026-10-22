"""FastAPI entry point for HomeBase Fit.

Run locally from backend/ (no auto-reload, so edits never spawn extra servers):
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import MODEL_NAME, llm_provider

app = FastAPI(title="HomeBase Fit API")

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

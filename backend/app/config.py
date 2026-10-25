"""Settings shared by the API, the MCP server, and the agents.

Secrets come only from the environment or a .env file, never from source.
Lookup order for each key:
  1. a real environment variable (how a hosting platform provides it)
  2. <project root>/.env
  3. the folder one level above the project root (e.g. a "submissions" dir)
In production (APP_ENV=production set as a real environment variable) only step 1 is used: a .env file lying
around on a server is never read.
"""

import os
from pathlib import Path

from dotenv import dotenv_values

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
PROMPTS_DIR = BACKEND_DIR / "prompts"
CONTENT_DIR = PROJECT_ROOT / "content"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"   # the built React app (npm run build); served by FastAPI

MIGRATIONS_DIR = BACKEND_DIR / "migrations"   # Alembic (schema); content is seeded from content/ by app/db/seed.py

ENV_PATHS = (PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env")

MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"


def _env_only() -> bool:
    """Production reads real environment variables only (checked without get_secret, to avoid recursion)."""
    return (os.getenv("APP_ENV") or "").strip().lower() == "production"


def get_secret(name: str) -> str | None:
    """Return a secret by name, or None if it is not set anywhere."""
    value = os.getenv(name)
    for path in () if _env_only() else ENV_PATHS:
        if value:
            break
        if path.exists():
            value = dotenv_values(path).get(name)
    return value or None


# The database: Postgres at DATABASE_URL (Neon in production, since 2026-10-25; it replaced the SQLite file on a Render
# disk). A secret (it holds the password), looked up like the others. Tests point it at a throwaway database by
# setting DATABASE_URL_OVERRIDE (tests/conftest.py); nothing else should.
DATABASE_URL_OVERRIDE: str | None = None


def database_url() -> str:
    url = DATABASE_URL_OVERRIDE or get_secret("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Point it at a Postgres database (see .env.example and README.md).")
    # Some hosts hand out postgres://...; psycopg wants postgresql://.
    return "postgresql://" + url[len("postgres://"):] if url.startswith("postgres://") else url


_dev_secret: str | None = None


def app_secret_key() -> str:
    """Signs login tokens. Required in production; in dev a random per-process
    key is used if unset (so tokens stop working when the server restarts)."""
    global _dev_secret
    key = get_secret("APP_SECRET_KEY")
    if key:
        return key
    if is_production():
        raise RuntimeError("APP_SECRET_KEY must be set in production.")
    if _dev_secret is None:
        import secrets
        import warnings
        _dev_secret = secrets.token_hex(32)
        warnings.warn("APP_SECRET_KEY not set; using a temporary key. Sign-ins reset when the server restarts.")
    return _dev_secret


def is_production() -> bool:
    """APP_ENV=production turns off dev-only routes like /api/debug/*."""
    return (get_secret("APP_ENV") or "development").lower() == "production"


def llm_provider() -> str | None:
    """Which gateway the agents will use: "portkey", "openai", or None."""
    if get_secret("PORTKEY_API_KEY"):
        return "portkey"
    if get_secret("OPENAI_API_KEY"):
        return "openai"
    return None

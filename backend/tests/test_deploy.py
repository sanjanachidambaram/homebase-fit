"""Deployment: what a fresh Render instance does.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_deploy.py -v

- Everything lives in Postgres at DATABASE_URL (Neon); the service keeps nothing on local disk, so it runs on Render's
  free plan with no persistent disk. A brand-new, empty database is built on startup (Alembic migrations, then the
  content from content/), and the app works end to end.
- A normal redeploy leaves the data alone; a deploy with new content reloads the content and keeps every account.
- Production reads secrets from real environment variables only, never from a stray .env file.
- One service serves the API, the media in content/, and the built React app (with client-side routes).
"""

import subprocess

import pytest
import yaml
from fastapi.testclient import TestClient

from app import config
from app.db import META_KEY, connect, ensure_database, table_counts
from tests.helpers import quiz_answers


def counts() -> dict[str, int]:
    conn = connect()
    try:
        return table_counts(conn)
    finally:
        conn.close()


def run(sql, *args):
    conn = connect()
    try:
        with conn:
            return [tuple(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def test_no_database_file_in_the_repo_or_the_config():
    tracked = subprocess.run(["git", "ls-files"], cwd=config.PROJECT_ROOT, capture_output=True, text=True,
                             check=True).stdout.splitlines()
    assert not [f for f in tracked if f.endswith((".db", ".sqlite", ".sqlite3"))]   # no SQLite anywhere
    assert "backend/app/db/schema.sql" not in tracked                              # the schema is the migrations now
    for gone in ("WORKING_DB", "ORIGINAL_DB", "DB_DIR"):
        assert not hasattr(config, gone), gone
    app_code = "\n".join(f.read_text(encoding="utf-8") for f in (config.BACKEND_DIR / "app").rglob("*.py")
                         if f.name != "import_sqlite.py")                         # the one-time import reads a file
    assert "HOMEBASE_DB_PATH" not in app_code and "import sqlite3" not in app_code


def test_without_database_url_the_app_says_so(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL_OVERRIDE", None)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(config, "ENV_PATHS", ())
    with pytest.raises(RuntimeError, match="DATABASE_URL is not set"):
        config.database_url()
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host/db")                 # Heroku-style scheme is accepted
    assert config.database_url() == "postgresql://u:p@host/db"


def test_startup_builds_an_empty_database(empty_db):
    assert ensure_database() == "seeded"
    got = counts()
    for t in ("users", "oauth_identities", "calendar_entries", "goal_protocols", "exercises", "sources", "agent_runs",
              "app_meta"):
        assert t in got, t
    assert "basics_articles" not in got                                 # Workout Basics was removed 2026-10-25
    assert got["exercises"] == 903 and got["goal_protocols"] == 9 and got["users"] == 0
    assert run("SELECT version_num FROM alembic_version") == [("0002",)]


def test_migrations_go_down_and_up_cleanly(empty_db):
    from alembic import command
    from app.db.migrate import alembic_config
    ensure_database()
    command.downgrade(alembic_config(), "base")
    assert set(counts()) == set()                                       # every table gone
    command.upgrade(alembic_config(), "head")
    assert {"users", "oauth_identities", "exercises"} <= set(counts())


def test_a_fresh_instance_works_end_to_end(empty_db, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "deploy-test-secret")
    from app.main import app
    from app.security import limiter
    limiter.reset()
    with TestClient(app) as client:                                     # startup (lifespan) builds the database
        r = client.post("/api/users", json={"username": "fresh", "first_name": "Tester", "password": "correct horse 1"}).json()
        h = {"Authorization": f"Bearer {r['token']}"}
        assert client.put(f"/api/users/{r['user_id']}/quiz-profile", headers=h, json={
            "consent_accepted": True, "consent_version": "t", "answers": quiz_answers()}).status_code == 200
        assert client.get("/api/plan", headers=h).json()["generated"] is True
        assert len(client.get("/api/calendar", headers=h).json()["entries"]) >= 1
        assert client.post("/api/favorites", headers=h, json={"exercise_id": "glute_bridge"}).status_code == 200
        assert client.get("/api/data-summary").json()["exercises"]["total"] == 903


def test_a_normal_redeploy_leaves_the_data_alone(empty_db):
    ensure_database()
    run("INSERT INTO users (username, first_name, password_hash) VALUES ('survivor', 'Tester', 'x')")
    run("INSERT INTO exercise_favorites (user_id, exercise_id) SELECT id, 'glute_bridge' FROM users")
    before = counts()
    for _ in range(3):                                                  # three restarts / redeploys, same content
        assert ensure_database() == "unchanged"
    assert counts() == before


def test_a_deploy_with_new_content_reloads_it_and_keeps_every_account(empty_db):
    ensure_database()
    run("INSERT INTO users (username, first_name, password_hash) VALUES ('keepme', 'Tester', 'x')")
    run("INSERT INTO exercise_favorites (user_id, exercise_id) SELECT id, 'glute_bridge' FROM users")
    run("UPDATE sources SET name = 'Stale name' WHERE id = 'free-exercise-db'")
    run("UPDATE app_meta SET value = 'an older deploy' WHERE key = ?", META_KEY)   # as if content/ changed since

    assert ensure_database() == "refreshed"
    assert run("SELECT username::text FROM users") == [("keepme",)]                # the account survived
    assert run("SELECT exercise_id FROM exercise_favorites") == [("glute_bridge",)]
    assert run("SELECT name FROM sources WHERE id = 'free-exercise-db'") != [("Stale name",)]   # content reloaded
    assert counts()["exercises"] == 903
    assert ensure_database() == "unchanged"                             # and the next restart leaves it alone


def test_production_never_reads_a_dotenv_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("APP_SECRET_KEY=from-a-file\nPORTKEY_API_KEY=file-key\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_PATHS", (env_file,))
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    monkeypatch.delenv("PORTKEY_API_KEY", raising=False)

    monkeypatch.setenv("APP_ENV", "development")
    assert config.get_secret("APP_SECRET_KEY") == "from-a-file"          # local dev: .env works as before

    monkeypatch.setenv("APP_ENV", "production")
    assert config.get_secret("APP_SECRET_KEY") is None                  # production: environment only
    assert config.get_secret("PORTKEY_API_KEY") is None
    with pytest.raises(RuntimeError, match="APP_SECRET_KEY must be set"):
        config.app_secret_key()
    monkeypatch.setenv("APP_SECRET_KEY", "from-the-environment")
    assert config.app_secret_key() == "from-the-environment"


# ---------------------------------------------------------------- one service: API + media + the built app

built = pytest.mark.skipif(not (config.FRONTEND_DIST / "index.html").exists(),
                           reason="frontend not built (run npm run build in frontend/)")


@built
@pytest.mark.parametrize("path", ["/", "/calendar", "/about", "/about/data", "/exercises", "/pregnancy-support",
                                  "/how-we-build", "/some/unknown/page"])
def test_app_routes_get_the_react_app(client, path):
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert '<div id="root">' in r.text and r.headers["cache-control"] == "no-cache"


@built
def test_built_assets_and_root_files_are_served(client):
    html = client.get("/").text
    js = html.split('src="')[1].split('"')[0]                            # /assets/index-<hash>.js
    assert js.startswith("/assets/")
    r = client.get(js)
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert client.get("/favicon.svg").headers["content-type"].startswith("image/svg")


@built
def test_api_and_media_win_over_the_app(client):
    assert client.get("/api/health").json()["status"] == "ok"
    missing = client.get("/api/does-not-exist")
    assert missing.status_code == 404 and missing.headers["content-type"] == "application/json"
    img = client.get("/content/exercises/source_free_exercise_db/images/3_4_Sit-Up/0.jpg")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and len(img.content) > 1000
    assert client.get("/content/images/team/README.md").status_code == 200
    assert client.get("/content/nope.jpg").status_code == 404


def test_the_old_combined_plan_page_address_goes_to_the_plan(client):
    r = client.get("/content", follow_redirects=False)                  # "Your Plan & Basics" used to live here
    assert r.status_code == 301 and r.headers["location"] == "/plan"
    assert client.get("/content/images/team/README.md").status_code == 200   # the media mount is untouched


@built
def test_no_files_outside_the_built_app(client):
    for path in ("/..%2Fbackend%2Fapp%2Fconfig.py", "/../backend/app/config.py", "/%2e%2e/%2e%2e/.env"):
        r = client.get(path)
        assert "get_secret" not in r.text and "PORTKEY" not in r.text, path


def test_render_yaml_is_free_with_no_disk_and_the_database_in_postgres():
    spec = yaml.safe_load((config.PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    assert len(spec["services"]) == 1                                   # one service: FastAPI serves the built app
    web = spec["services"][0]
    assert (web["type"], web["name"], web["runtime"]) == ("web", "bee-fit", "python")   # renamed from homebase-fit
    assert web["plan"] == "free"                                        # nothing on local disk to keep
    assert "disk" not in web
    assert web["buildCommand"] == "pip install -r backend/requirements.txt && cd frontend && npm ci && npm run build"
    assert web["startCommand"] == ("cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT "
                                   "--proxy-headers --forwarded-allow-ips '*'")   # real client IPs for rate limits
    assert web["healthCheckPath"] == "/api/health"
    env = {e["key"]: e for e in web["envVars"]}
    assert "HOMEBASE_DB_PATH" not in env
    assert env["PUBLIC_BASE_URL"] == {"key": "PUBLIC_BASE_URL", "value": "https://bee-fit.onrender.com"}
    for secret in ("APP_ENV", "APP_SECRET_KEY", "PORTKEY_API_KEY", "DATABASE_URL", "GOOGLE_CLIENT_ID",
                   "GOOGLE_CLIENT_SECRET", "MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"):
        assert env[secret] == {"key": secret, "sync": False}              # set in the dashboard, never here
    assert {k for k, e in env.items() if "value" in e} == {"PUBLIC_BASE_URL"}   # the only non-secret value
    assert "OPENAI_API_KEY" not in env                                  # only set if the project owner asks

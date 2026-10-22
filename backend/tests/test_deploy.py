"""Deployment: what a fresh Render instance does.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest tests/test_deploy.py -v

- A brand-new instance has no working database (it's not in git): startup must build it from
  homebase_original.db with every table (calendar_entries, goal_protocols, ...) and the app must work end to end.
- Production reads secrets from real environment variables only, never from a stray .env file.
- One service serves the API, the media in content/, and the built React app (with client-side routes).
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import ensure_working_db
from tests.helpers import quiz_answers


def tables(path) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return {n: conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
    finally:
        conn.close()


@pytest.fixture
def fresh_instance(tmp_path, monkeypatch):
    """No working database at all, like a new deploy (homebase.db is gitignored)."""
    path = tmp_path / "fresh" / "homebase.db"
    path.parent.mkdir()
    monkeypatch.setattr(config, "WORKING_DB", path)
    monkeypatch.setenv("APP_SECRET_KEY", "deploy-test-secret")
    assert not path.exists()
    return path


def test_working_db_is_not_in_git():
    ignore = (config.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "backend/app/db/homebase.db" in ignore.splitlines()


def test_startup_builds_the_working_db_from_the_original(fresh_instance):
    ensure_working_db()
    got, want = tables(fresh_instance), tables(config.ORIGINAL_DB)
    assert got == want                                                  # same tables, same seeded content
    for t in ("calendar_entries", "goal_protocols", "exercises", "sources", "basics_articles", "agent_runs"):
        assert t in got, t
    assert got["exercises"] == 903 and got["goal_protocols"] == 15 and got["users"] == 0


def test_a_fresh_instance_works_end_to_end(fresh_instance):
    from app.main import app
    with TestClient(app) as client:                                     # startup (lifespan) creates the DB
        assert fresh_instance.exists()
        r = client.post("/api/users", json={"email": "fresh@example.com", "password": "correct horse 1"}).json()
        h = {"Authorization": f"Bearer {r['token']}"}
        assert client.put(f"/api/users/{r['user_id']}/quiz-profile", headers=h, json={
            "consent_accepted": True, "consent_version": "t", "answers": quiz_answers()}).status_code == 200
        assert client.get("/api/plan", headers=h).json()["generated"] is True
        assert len(client.get("/api/calendar", headers=h).json()["entries"]) >= 1
        assert client.post("/api/favorites", headers=h, json={"exercise_id": "glute_bridge"}).status_code == 200
        assert client.get("/api/data-summary").json()["exercises"]["total"] == 903


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


@built
def test_no_files_outside_the_built_app(client):
    for path in ("/..%2Fbackend%2Fapp%2Fconfig.py", "/../backend/app/config.py", "/%2e%2e/%2e%2e/.env"):
        r = client.get(path)
        assert "get_secret" not in r.text and "PORTKEY" not in r.text, path

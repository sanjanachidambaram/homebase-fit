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
    assert ensure_working_db() == "created"
    got, want = tables(fresh_instance), tables(config.ORIGINAL_DB)
    assert got.pop("app_meta") == 1 and want.pop("app_meta") == 0      # the copy records which original it came from
    assert got == want                                                  # same tables, same seeded content
    for t in ("calendar_entries", "goal_protocols", "exercises", "sources", "basics_articles", "agent_runs"):
        assert t in got, t
    assert got["exercises"] == 903 and got["goal_protocols"] == 9 and got["users"] == 0


def test_a_fresh_instance_works_end_to_end(fresh_instance):
    from app.main import app
    with TestClient(app) as client:                                     # startup (lifespan) creates the DB
        assert fresh_instance.exists()
        r = client.post("/api/users", json={"username": "fresh", "first_name": "Tester", "password": "correct horse 1"}).json()
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


def test_the_old_combined_plan_page_address_goes_to_the_plan(client):
    r = client.get("/content", follow_redirects=False)                  # "Your Plan & Basics" used to live here
    assert r.status_code == 301 and r.headers["location"] == "/plan"
    assert client.get("/content/images/team/README.md").status_code == 200   # the media mount is untouched


@built
def test_no_files_outside_the_built_app(client):
    for path in ("/..%2Fbackend%2Fapp%2Fconfig.py", "/../backend/app/config.py", "/%2e%2e/%2e%2e/.env"):
        r = client.get(path)
        assert "get_secret" not in r.text and "PORTKEY" not in r.text, path


# ---------------------------------------------------------------- the persistent disk (paid Render instance)

import yaml  # noqa: E402

from app.db import copy_db, original_fingerprint, working_db_stamp  # noqa: E402


@pytest.fixture
def disk(tmp_path, monkeypatch):
    """A brand-new, empty persistent disk, with HOMEBASE_DB_PATH pointing at a file on it (like /var/data)."""
    mount = tmp_path / "var" / "data"
    monkeypatch.setattr(config, "WORKING_DB", mount / "homebase.db")
    monkeypatch.setenv("APP_SECRET_KEY", "disk-test-secret")
    return mount


def add_user(username):
    conn = sqlite3.connect(config.WORKING_DB)
    with conn:
        conn.execute("INSERT INTO users (username, first_name, password_hash) VALUES (?, 'Tester', 'x')", (username,))
    conn.close()


def users():
    conn = sqlite3.connect(config.WORKING_DB)
    try:
        return [r[0] for r in conn.execute("SELECT username FROM users ORDER BY id")]
    finally:
        conn.close()


def test_first_use_of_an_empty_disk_builds_the_db_there(disk):
    assert not disk.exists()                                            # not even the folder yet
    assert ensure_working_db() == "created"
    assert (disk / "homebase.db").exists() and working_db_stamp() == original_fingerprint()
    assert tables(disk / "homebase.db")["exercises"] == 903


def test_a_normal_redeploy_leaves_the_data_alone(disk):
    ensure_working_db()
    add_user("survivor")
    before = (disk / "homebase.db").read_bytes()
    for _ in range(3):                                                  # three restarts / redeploys, same content
        assert ensure_working_db() == "unchanged"
    assert (disk / "homebase.db").read_bytes() == before and users() == ["survivor"]
    assert not list(disk.glob("*before-refresh*"))                      # nothing to back up, nothing touched


def test_a_deploy_with_new_content_refreshes_but_keeps_accounts_and_a_backup(disk, tmp_path, monkeypatch):
    ensure_working_db()
    add_user("keepme")
    new_original = tmp_path / "new_original.db"                         # this deploy ships new content
    copy_db(config.ORIGINAL_DB, new_original)
    conn = sqlite3.connect(new_original)
    with conn:
        conn.execute("UPDATE sources SET name = 'Renamed in a new deploy' WHERE id = 'free-exercise-db'")
    conn.close()
    monkeypatch.setattr(config, "ORIGINAL_DB", new_original)

    assert ensure_working_db() == "refreshed"
    assert users() == ["keepme"]                            # the account survived
    conn = sqlite3.connect(config.WORKING_DB)
    assert conn.execute("SELECT name FROM sources WHERE id = 'free-exercise-db'").fetchone()[0] == "Renamed in a new deploy"
    conn.close()
    backups = list(disk.glob("homebase.before-refresh-*.db"))
    assert len(backups) == 1 and "keepme" in [r[0] for r in sqlite3.connect(backups[0]).execute("SELECT username FROM users")]
    assert ensure_working_db() == "unchanged"                           # and the next restart leaves it alone


def test_a_working_db_from_before_this_change_is_upgraded_not_wiped(disk):
    ensure_working_db()
    add_user("old-timer")
    conn = sqlite3.connect(config.WORKING_DB)
    with conn:
        conn.execute("DROP TABLE app_meta")                             # what the live DB looked like before
    conn.close()
    assert ensure_working_db() == "refreshed" and users() == ["old-timer"]
    assert working_db_stamp() == original_fingerprint()


def test_render_yaml_puts_the_database_on_a_persistent_disk():
    spec = yaml.safe_load((config.PROJECT_ROOT / "render.yaml").read_text(encoding="utf-8"))
    web = spec["services"][0]
    assert web["plan"] == "starter"                                     # paid: disks aren't available on free
    assert web["disk"] == {"name": "homebase-data", "mountPath": "/var/data", "sizeGB": 1}
    env = {e["key"]: e for e in web["envVars"]}
    assert env["HOMEBASE_DB_PATH"]["value"] == "/var/data/homebase.db"  # on the disk, so it survives deploys
    assert env["HOMEBASE_DB_PATH"]["value"].startswith(web["disk"]["mountPath"] + "/")
    for secret in ("APP_ENV", "APP_SECRET_KEY", "PORTKEY_API_KEY"):
        assert env[secret] == {"key": secret, "sync": False}              # still set in the dashboard, never here


def test_local_dev_still_uses_the_normal_local_path():
    """Without HOMEBASE_DB_PATH (local dev), the working DB is backend/app/db/homebase.db, as it always was."""
    import os
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if k not in ("HOMEBASE_DB_PATH", "APP_ENV")}   # plain local dev
    out = subprocess.run([sys.executable, "-c", "from app import config; print(config.WORKING_DB)"],
                         cwd=config.BACKEND_DIR, env=env, capture_output=True, text=True, check=True).stdout.strip()
    assert out == str(config.DB_DIR / "homebase.db")

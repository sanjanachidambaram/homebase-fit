"""Exercise detail (with media_type and review fields) and favorites.

Run from backend/:
    .venv\\Scripts\\python.exe -m pytest -v
"""

from app.db import IntegrityError

FEDB_ID = "3_4_Sit-Up"   # imported exercise with a real image file
PLACEHOLDER_ID = "glute_bridge"   # hand-authored; its demo file doesn't exist yet


def sign_up(client, username):
    r = client.post("/api/users", json={"username": username, "first_name": "Tester", "password": "correct horse 1"})
    assert r.status_code == 201, r.text
    body = r.json()
    return body["user_id"], {"Authorization": f"Bearer {body['token']}"}


# ---------------------------------------------------------------- detail

def test_detail_has_full_info_and_review_fields(client):
    d = client.get(f"/api/exercises/{FEDB_ID}").json()
    for key in ("name", "muscle_group", "equipment_needed", "difficulty", "instructions", "primary_muscles",
                "secondary_muscles", "demo_media_url", "media_type", "source_dataset", "source", "status",
                "review_notice", "citations", "contraindication_status"):
        assert key in d, key
    assert d["source_dataset"] == "free-exercise-db"
    assert d["source"]["url"] == "https://github.com/yuhonas/free-exercise-db"
    assert d["media_type"] == "image"
    assert d["demo_media_url"].endswith(".jpg") and client.get(d["demo_media_url"]).status_code == 200
    assert d["status"] == "placeholder" and d["review_notice"] == "Content pending expert review"
    assert d["citations"] == []


def test_media_type_is_none_until_the_file_exists(client):
    d = client.get(f"/api/exercises/{PLACEHOLDER_ID}").json()
    assert d["demo_media_url"] is None and d["media_type"] is None
    assert d["source_dataset"] == "placeholder-authored"


def test_media_type_comes_from_the_file_extension():
    from app.db.seed import media_type_for
    assert media_type_for("a/b.jpg") == "image" and media_type_for("a/b.PNG") == "image"
    assert media_type_for("a/b.gif") == "gif"
    assert media_type_for("a/b.mp4") == "video" and media_type_for("a/b.webm") == "video"
    assert media_type_for(None) is None


def test_media_type_is_stored_for_every_exercise_with_a_path(test_db):
    from app.db import connect
    conn = connect()
    assert conn.execute("SELECT COUNT(*) FROM exercises WHERE demo_media_path IS NOT NULL AND media_type IS NULL"
                        ).fetchone()[0] == 0
    conn.close()


def test_detail_404_and_list_uses_the_same_shape(client):
    assert client.get("/api/exercises/not_a_real_exercise").status_code == 404
    items = client.get("/api/exercises?group=upper").json()
    assert items and all("media_type" in i and "source" in i and "citations" in i for i in items)


# ---------------------------------------------------------------- favorites

def test_favorites_require_sign_in(client):
    assert client.get("/api/favorites").status_code == 401
    assert client.post("/api/favorites", json={"exercise_id": FEDB_ID}).status_code == 401
    assert client.delete(f"/api/favorites/{FEDB_ID}").status_code == 401


def test_add_list_remove_favorite(client):
    _, h = sign_up(client, "user_a")
    assert client.get("/api/favorites", headers=h).json() == []

    r = client.post("/api/favorites", json={"exercise_id": FEDB_ID}, headers=h)
    assert r.status_code == 200 and r.json()["favorited"] is True
    client.post("/api/favorites", json={"exercise_id": PLACEHOLDER_ID}, headers=h)

    favs = client.get("/api/favorites", headers=h).json()
    assert [f["id"] for f in favs] == [PLACEHOLDER_ID, FEDB_ID]          # newest first
    assert favs[1]["instructions"] and favs[1]["demo_media_url"]           # full detail, not just ids

    assert client.delete(f"/api/favorites/{FEDB_ID}", headers=h).json()["favorited"] is False
    assert [f["id"] for f in client.get("/api/favorites", headers=h).json()] == [PLACEHOLDER_ID]


def test_favorite_is_idempotent_and_unique(client):
    uid, h = sign_up(client, "user_a")
    for _ in range(3):
        assert client.post("/api/favorites", json={"exercise_id": FEDB_ID}, headers=h).status_code == 200
    assert len(client.get("/api/favorites", headers=h).json()) == 1
    assert client.delete(f"/api/favorites/{FEDB_ID}", headers=h).status_code == 200
    assert client.delete(f"/api/favorites/{FEDB_ID}", headers=h).status_code == 200   # already gone is fine

    from app.db import connect
    conn = connect()
    conn.execute("INSERT INTO exercise_favorites (user_id, exercise_id) VALUES (?, ?)", (uid, FEDB_ID))
    try:
        conn.execute("INSERT INTO exercise_favorites (user_id, exercise_id) VALUES (?, ?)", (uid, FEDB_ID))
        raise AssertionError("duplicate favorite should be rejected by the UNIQUE constraint")
    except IntegrityError:
        pass
    conn.close()


def test_unknown_exercise_cant_be_favorited(client):
    _, h = sign_up(client, "user_a")
    assert client.post("/api/favorites", json={"exercise_id": "nope"}, headers=h).status_code == 404


def test_favorites_are_private_per_user(client):
    _, ha = sign_up(client, "user_a")
    _, hb = sign_up(client, "user_b")
    client.post("/api/favorites", json={"exercise_id": FEDB_ID}, headers=ha)
    assert client.get("/api/favorites", headers=hb).json() == []
    client.delete(f"/api/favorites/{FEDB_ID}", headers=hb)      # B can't un-fave A's favorite
    assert len(client.get("/api/favorites", headers=ha).json()) == 1


def test_deleted_account_cant_favorite_with_its_old_token(client):
    uid, h = sign_up(client, "user_a")
    assert client.delete(f"/api/users/{uid}", headers=h).status_code == 200
    assert client.post("/api/favorites", json={"exercise_id": FEDB_ID}, headers=h).status_code == 401

"""GET /api/data-summary: the About page's live numbers. Each count is checked against the database directly,
so the page can never show a stale or invented figure.

Run from backend/:
    .venv\Scripts\python.exe -m pytest tests/test_about_data.py -v
"""

from app.db import connect


def one(sql):
    conn = connect()
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def test_summary_matches_the_database(client):
    d = client.get("/api/data-summary").json()
    ex = d["exercises"]
    assert ex["total"] == one("SELECT COUNT(*) FROM exercises") == 903
    assert {s["id"]: s["count"] for s in ex["by_source"]} == {"free-exercise-db": 876, "placeholder-authored": 27}
    assert sum(s["count"] for s in ex["by_source"]) == ex["total"]
    assert ex["injury_checked"] + ex["injury_unchecked"] == ex["total"]
    assert (ex["injury_checked"], ex["with_cautions"], ex["cautions"]) == (27, 17, 30)
    assert (ex["reasons_ai_drafted"], ex["reasons_pt_reviewed"], ex["injury_pt_reviewed"]) == (30, 0, 0)
    assert d["protocols"] == {"total": 15, "placeholder": 15, "with_citations": 0}
    assert d["basics_articles"] == {"total": 5, "placeholder": 5}


def test_summary_follows_the_data(client):
    """No hardcoded numbers: tag one more imported exercise and the counts move."""
    conn = connect()
    with conn:
        conn.execute("UPDATE exercises SET contraindication_status = 'draft', injury_contraindications = '[\"knee\"]', "
                     "injury_rationale = '{\"knee\": {\"reasoning\": \"x\", \"tier\": \"ai_drafted\", \"source\": \"y\"}}' "
                     "WHERE id = '3_4_Sit-Up'")
    conn.close()
    ex = client.get("/api/data-summary").json()["exercises"]
    assert (ex["injury_checked"], ex["with_cautions"], ex["cautions"], ex["reasons_ai_drafted"]) == (28, 18, 31, 31)

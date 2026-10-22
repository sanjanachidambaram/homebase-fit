"""Smoke test for the HomeBase Fit MCP server.

Starts the server exactly as .mcp.json describes it (a real stdio subprocess, the same way Claude Code
launches it), calls all 7 tools over the MCP protocol, and checks the answers. In particular it proves
the injury filter really removes a contraindicated exercise.

Safe by design: user-data tools need a user and logs, and the injury proof needs a tagged exercise, so
those run against a THROWAWAY COPY of the database (HOMEBASE_DB_PATH). The committed databases are never
modified. A last step repeats the injury check against the real, unmodified working database.

Run from the project root:
    backend/.venv/Scripts/python.exe backend/app/mcp_server/smoke_test.py
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from fastmcp import Client  # noqa: E402

from app.config import ORIGINAL_DB  # noqa: E402
from app.db import connect, copy_db  # noqa: E402

TEST_EXERCISE = "Adductor"          # an imported exercise we tag for the test (only in the throwaway copy)
EXPECTED_TOOLS = {"get_user_profile", "search_exercises", "search_program_templates", "search_basics_kb",
                  "get_progress_summary", "compute_strength_equivalents", "check_goal_achievement"}
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"   {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        failures.append(what)


def show(title: str) -> None:
    print(f"\n== {title}")


def build_throwaway_db(path: Path) -> int:
    """Copy of the clean DB + one tagged exercise + one test user with 30 days of activity."""
    copy_db(ORIGINAL_DB, path)
    conn = connect(path)
    today = datetime.now(timezone.utc)
    stamp = (today - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        conn.execute("UPDATE exercises SET injury_contraindications = '[\"knee\"]', contraindication_status = 'draft' "
                     "WHERE id = ?", (TEST_EXERCISE,))
        uid = conn.execute("INSERT INTO users (email, password_hash) VALUES ('smoke.test@example.com', 'x')").lastrowid
        conn.execute(
            "INSERT INTO quiz_profiles (user_id, goals, timeline, injury_flags, injury_notes, age, weight, height, "
            "consent_accepted, consent_accepted_at, consent_version, created_at, updated_at) "
            "VALUES (?, '[\"weight_loss\", \"strength\"]', '8_weeks', '[\"lower_back\"]', 'SMOKE-TEST-PRIVATE-NOTE', "
            "34, 165, 66, 1, ?, 'smoke', ?, ?)", (uid, stamp, stamp, stamp))
        for d in range(0, 18, 2):
            when = (today - timedelta(days=d)).date().isoformat()
            conn.execute("INSERT INTO workout_logs (user_id, date, exercise_id, sets, reps, weight_used) "
                         "VALUES (?, ?, 'goblet_squat', 3, 10, 25)", (uid, when))
        for d, w in ((20, 168.0), (10, 166.5), (0, 165.0)):
            conn.execute("INSERT INTO measurements (user_id, date, body_weight, measurements) VALUES (?, ?, ?, '{}')",
                         (uid, (today - timedelta(days=d)).date().isoformat(), w))
    conn.close()
    return uid


def server_config(env: dict[str, str] | None) -> dict:
    """The server entry from .mcp.json, as Claude Code reads it (optionally with an env override)."""
    config = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))
    entry = config["mcpServers"]["homebase-fit"]
    if env:
        entry["env"] = {**os.environ, **env}   # a child with an env block gets only that env, so keep PATH etc.
    return config


async def main() -> None:
    os.chdir(ROOT)   # .mcp.json paths are relative to the project root
    tmp = Path(tempfile.mkdtemp(prefix="homebase_smoke_")) / "smoke.db"
    uid = build_throwaway_db(tmp)
    print(f"Throwaway database: {tmp}\n(test user id {uid}; exercise '{TEST_EXERCISE}' tagged unsafe for knee)")

    async with Client(server_config({"HOMEBASE_DB_PATH": str(tmp)})) as c:
        show("tools/list")
        tools = await c.list_tools()
        names = {t.name for t in tools}
        print("   ", sorted(names))
        check(names == EXPECTED_TOOLS, "exactly the 7 expected tools")
        check(all(t.annotations and t.annotations.read_only_hint for t in tools), "every tool is marked read-only")

        show("1. get_user_profile")
        p = (await c.call_tool("get_user_profile", {"user_id": uid})).data
        print("   ", json.dumps(p))
        check(set(p) == {"found", "goals", "timeline", "injury_flags", "age", "weight_lb", "height_in"},
              "only goals/timeline/injury_flags/age/weight/height returned")
        check("SMOKE-TEST-PRIVATE-NOTE" not in json.dumps(p) and "smoke.test" not in json.dumps(p),
              "no email and no free-text injury note")

        show("2. search_exercises: THE INJURY FILTER (legs, with and without injury_flags=['knee'])")
        plain = (await c.call_tool("search_exercises", {"muscle_group": "legs", "limit": 50})).data
        knee = (await c.call_tool("search_exercises", {"muscle_group": "legs", "injury_flags": ["knee"],
                                                       "limit": 50})).data
        plain_ids = {e["id"] for e in plain["exercises"]}
        knee_ids = {e["id"] for e in knee["exercises"]}
        print(f"    without filter: {plain['total_matching']} legs exercises")
        print(f"    with knee flag: {knee['total_matching']} legs exercises "
              f"({knee['injury_filter']['excluded_as_contraindicated']} excluded)")
        removed = sorted(plain_ids - knee_ids)
        print(f"    removed by the filter: {removed}")
        check(TEST_EXERCISE in plain_ids and TEST_EXERCISE not in knee_ids, f"tagged test exercise '{TEST_EXERCISE}' is excluded")
        check({"bodyweight_squat", "reverse_lunge", "wall_sit", "goblet_squat"} <= set(removed),
              "the 4 drafted knee-unsafe exercises are excluded too")
        unchecked = next(e for e in knee["exercises"] if e["injury_unchecked"])
        print(f"    an unchecked exercise: {unchecked['name']!r} -> injury_check={unchecked['injury_check']!r}; "
              f"{unchecked['injury_note']}")
        check(unchecked["injury_check"] == "not_yet_checked" and unchecked["status"] == "placeholder"
              and "citations" in unchecked, "untagged exercises are flagged 'not_yet_checked' with status/citations")
        only = (await c.call_tool("search_exercises", {"muscle_group": "legs", "injury_flags": ["knee"],
                                                       "checked_only": True})).data
        check(only["count"] > 0 and not any(e["injury_unchecked"] for e in only["exercises"]),
              "checked_only=true returns only exercises that have injury tags")

        show("3. search_program_templates (goal weight_loss+rehab, injury lower_back)")
        progs = (await c.call_tool("search_program_templates", {"goal_tags": ["weight_loss", "rehab"],
                                                                "injury_flags": ["lower_back"]})).data
        print("    returned:", [p["name"] for p in progs["programs"]])
        print("    excluded:", [(x["name"], x["because_exercises"]) for x in progs["injury_filter"]["excluded_programs"]])
        check([p["name"] for p in progs["programs"]] == ["Back-Friendly Fat Loss"], "only the lower-back-safe program remains")
        check(progs["programs"][0]["status"] == "placeholder" and progs["programs"][0]["review_notice"],
              "status and review notice included")

        show("4. search_basics_kb")
        kb = (await c.call_tool("search_basics_kb", {"query": "how long should I rest between sets?"})).data
        print("    top match:", kb["matches"][0]["title"], "| matched terms:", kb["matches"][0]["matched_terms"])
        none = (await c.call_tool("search_basics_kb", {"query": "quantum astrophysics"})).data
        print("    off-topic query ->", none["answerable"], "|", none["message"][:70] + "...")
        check(kb["matches"][0]["slug"] == "rest_between_sets", "finds the right article")
        check(none["answerable"] is False, "says so when nothing matches")

        show("5. get_progress_summary")
        s = (await c.call_tool("get_progress_summary", {"user_id": uid})).data
        print("   ", json.dumps({k: s[k] for k in ("sessions_logged", "total_weight_lifted_lbs",
                                                   "current_streak_days", "rest_day_suggested")}))
        print("    body weight:", json.dumps(s["body_weight_trend"]))
        check(s["sessions_logged"] == 9 and s["total_weight_lifted_lbs"] == 6750.0, "9 sessions, 9 x 750 = 6,750 lb")
        check(s["body_weight_trend"]["direction"] == "down" and s["body_weight_trend"]["change"] == -3.0,
              "body weight trend: 168 -> 165 = -3.0, down")

        show("6. compute_strength_equivalents (using the 6,750 lb above)")
        eq = (await c.call_tool("compute_strength_equivalents", {"total_weight_lifted_lbs": s["total_weight_lifted_lbs"]})).data
        print("   ", eq["headline"])
        for comp in eq["comparisons"]:
            print(f"      {comp['phrase']:<34} ({comp['unit_weight_lbs']:,} lb each)")
        check(eq["headline"] == "You've lifted about 1.4 full-size trees!",
              "headline = the biggest comparison reached (6,750 / 4,820 lb tree = 1.4)")
        check(all(comp["source"] for comp in eq["comparisons"]), "every comparison names its source")

        show("7. check_goal_achievement")
        g = (await c.call_tool("check_goal_achievement", {"user_id": uid})).data
        print("    status:", g["status"])
        for r in g["reasons"]:
            print("     -", r)
        check(g["status"] in {"on_track", "ahead", "behind", "insufficient_data"}, "returns a valid status")
        check(g["status"] == "on_track", "about 3 sessions/week vs a target of 3, and body weight down: on_track")

    show("Repeat of the injury check on the REAL, unmodified working database")
    async with Client(server_config(None)) as c:
        real = (await c.call_tool("search_exercises", {"muscle_group": "legs", "injury_flags": ["knee"],
                                                       "limit": 50})).data
        real_all = (await c.call_tool("search_exercises", {"muscle_group": "legs", "limit": 50})).data
        removed = sorted({e["id"] for e in real_all["exercises"]} - {e["id"] for e in real["exercises"]})
        print("    removed for knee:", removed)
        check({"bodyweight_squat", "wall_sit"} <= set(removed), "drafted knee-unsafe exercises excluded in the real DB")
        check(TEST_EXERCISE in {e["id"] for e in real["exercises"]}, f"'{TEST_EXERCISE}' is NOT tagged in the real DB (test tag stayed in the copy)")

    tmp.unlink(missing_ok=True)
    tmp.parent.rmdir()
    print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED: {failures}"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())

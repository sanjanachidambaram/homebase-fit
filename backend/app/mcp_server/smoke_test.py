"""Smoke test for the Bee Fit MCP server.

Starts the server exactly as .mcp.json describes it (a real stdio subprocess, the same way Claude Code
launches it), calls all 6 tools over the MCP protocol, and checks the answers. In particular it proves
the injury filter really removes a contraindicated exercise.

Safe by design: user-data tools need a user and logs, and the injury proof needs a tagged exercise, so
those run against a THROWAWAY Postgres database, created on the same server as DATABASE_URL (migrations + content,
exactly as the app builds one) and dropped at the end. The real database is never modified. A last step repeats the
injury check against the real, unmodified database.

Run from the project root:
    backend/.venv/Scripts/python.exe backend/app/mcp_server/smoke_test.py
"""

import asyncio
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend"))

from fastmcp import Client  # noqa: E402

from app import config  # noqa: E402
from app.db import close_pools, connect, ensure_database  # noqa: E402

TEST_EXERCISE = "Adductor"          # an imported exercise we tag for the test (only in the throwaway copy)
# Every exercise has drafted injury data since 2026-10-24, so the copy marks one as never checked, to show the tool
# still flags unchecked exercises instead of calling them safe.
UNCHECKED_EXERCISE = "glute_bridge"
EXPECTED_TOOLS = {"get_user_profile", "search_exercises",
                  "get_progress_summary", "compute_strength_equivalents", "check_goal_achievement"}
failures: list[str] = []


def check(ok: bool, what: str) -> None:
    print(f"   {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        failures.append(what)


def show(title: str) -> None:
    print(f"\n== {title}")


def create_throwaway_db() -> str:
    """A new, empty database on the DATABASE_URL server; returns its connection string."""
    real = config.database_url()
    name = f"beefit_smoke_{secrets.token_hex(4)}"
    with psycopg.connect(real, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    return psycopg.conninfo.make_conninfo(real, dbname=name)


def drop_throwaway_db(url: str) -> None:
    close_pools(url)
    name = psycopg.conninfo.conninfo_to_dict(url)["dbname"]
    with psycopg.connect(config.database_url(), autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def build_throwaway_db(url: str) -> int:
    """A freshly built DB + one tagged exercise + one test user with 30 days of activity."""
    config.DATABASE_URL_OVERRIDE = url
    try:
        ensure_database()
        return _add_test_data()
    finally:
        close_pools(url)
        config.DATABASE_URL_OVERRIDE = None


def _add_test_data() -> int:
    conn = connect()
    today = datetime.now(timezone.utc)
    stamp = (today - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        conn.execute("UPDATE exercises SET injury_contraindications = '[\"knee\"]', contraindication_status = 'draft' "
                     "WHERE id = ?", (TEST_EXERCISE,))
        conn.execute("UPDATE exercises SET contraindication_status = 'untagged' WHERE id = ?", (UNCHECKED_EXERCISE,))
        uid = conn.execute("INSERT INTO users (username, first_name, password_hash) VALUES ('smoke.test', 'Smokey', 'x')").lastrowid
        conn.execute(
            "INSERT INTO quiz_profiles (user_id, goal, injury_flags, weight, "
            "consent_accepted, consent_accepted_at, consent_version, created_at, updated_at) "
            "VALUES (?, 'lose_weight', '[\"lower_back\"]', "
            "165, 1, ?, 'smoke', ?, ?)", (uid, stamp, stamp, stamp))
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
    tmp = create_throwaway_db()
    try:
        await run_checks(tmp)
    finally:
        drop_throwaway_db(tmp)
    print("\n" + ("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED: {failures}"))
    sys.exit(1 if failures else 0)


async def run_checks(tmp: str) -> None:
    uid = build_throwaway_db(tmp)
    print(f"Throwaway database: {psycopg.conninfo.conninfo_to_dict(tmp)['dbname']}\n"
          f"(test user id {uid}; exercise '{TEST_EXERCISE}' tagged unsafe for knee)")

    async with Client(server_config({"DATABASE_URL": tmp})) as c:
        show("tools/list")
        tools = await c.list_tools()
        names = {t.name for t in tools}
        print("   ", sorted(names))
        check(names == EXPECTED_TOOLS, f"exactly the {len(EXPECTED_TOOLS)} expected tools")
        check(all(t.annotations and t.annotations.read_only_hint for t in tools), "every tool is marked read-only")

        show("1. get_user_profile")
        p = (await c.call_tool("get_user_profile", {"user_id": uid})).data
        print("   ", json.dumps(p))
        check(set(p) == {"found", "goal", "injury_flags"}, "only the goal and injury flags returned (no weight)")
        check("smoke.test" not in json.dumps(p) and "Smokey" not in json.dumps(p), "no username and no first name")

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
        # Checked exercises come first, so look where the unchecked one is easy to reach: legs moves on a mat.
        mat = (await c.call_tool("search_exercises", {"muscle_group": "legs", "equipment": ["mat"],
                                                      "injury_flags": ["knee"], "limit": 50})).data
        unchecked = next(e for e in mat["exercises"] if e["injury_unchecked"])
        print(f"    an unchecked exercise: {unchecked['name']!r} -> injury_check={unchecked['injury_check']!r}; "
              f"{unchecked['injury_note']}")
        check(unchecked["injury_check"] == "not_yet_checked" and unchecked["status"] == "placeholder"
              and "citations" in unchecked, "untagged exercises are flagged 'not_yet_checked' with status/citations")
        only = (await c.call_tool("search_exercises", {"muscle_group": "legs", "injury_flags": ["knee"],
                                                       "checked_only": True})).data
        check(only["count"] > 0 and not any(e["injury_unchecked"] for e in only["exercises"]),
              "checked_only=true returns only exercises that have injury tags")

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
        # The headline is a random pick among the highest tier the total reaches (app/mcp_server/strength.py).
        pick = next(comp for comp in eq["comparisons"] if comp["name"] == eq["headline_comparison"])
        check(eq["headline"] == f"You've lifted {pick['phrase']}!" and pick["name"] in eq["headline_options"],
              f"headline = a pick from the highest tier reached ({pick['name']}, of {eq['headline_options']})")
        check(all(comp["source"] for comp in eq["comparisons"]), "every comparison names its source")

        show("7. check_goal_achievement")
        g = (await c.call_tool("check_goal_achievement", {"user_id": uid})).data
        print("    status:", g["status"])
        for r in g["reasons"]:
            print("     -", r)
        check(g["status"] in {"on_track", "ahead", "behind", "insufficient_data"}, "returns a valid status")
        check(g["status"] == "on_track", "about 3 sessions/week vs a target of 3, and body weight down: on_track")

    show("Repeat of the injury check on the REAL, unmodified working database")
    async with Client(server_config({"DATABASE_URL": config.database_url()})) as c:   # the real one, read-only
        real = (await c.call_tool("search_exercises", {"muscle_group": "legs", "injury_flags": ["knee"],
                                                       "limit": 50})).data
        real_all = (await c.call_tool("search_exercises", {"muscle_group": "legs", "limit": 50})).data
        removed = sorted({e["id"] for e in real_all["exercises"]} - {e["id"] for e in real["exercises"]})
        print("    removed for knee:", removed)
        check({"bodyweight_squat", "wall_sit"} <= set(removed), "drafted knee-unsafe exercises excluded in the real DB")
        check(TEST_EXERCISE in {e["id"] for e in real["exercises"]}, f"'{TEST_EXERCISE}' is NOT tagged in the real DB (test tag stayed in the copy)")


if __name__ == "__main__":
    asyncio.run(main())

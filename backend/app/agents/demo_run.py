"""Real end-to-end run of all four agents (real gpt-6-luna via Portkey), through the real HTTP routes.

Run from backend/:
    .venv\\Scripts\\python.exe -m app.agents.demo_run           # deletes the demo account at the end
    .venv\\Scripts\\python.exe -m app.agents.demo_run --keep    # keeps it (to look at in the app or DB)

What it does, against the working database:
  1. Signs up a demo account and takes the quiz (goals: weight loss + rehab; injury: lower back).
  2. Adds 11 straight days of demo workout logs and two weigh-ins (there's no logging page yet).
  3. Calls each agent route as that user, plus one red-flag Workout Basics question, and prints what happened.
  4. Prints the agent_runs rows (real token counts) and writes the transcript to output/agent_demo_run.json.
  5. Deletes the demo account through DELETE /api/users/{id}. Its agent_runs rows are kept, unlinked.
This spends real tokens (a few cents at most).
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT
from app.db import connect
from app.main import app

OUT = PROJECT_ROOT / "output" / "agent_demo_run.json"
CALLS = [
    ("Program Architect", "POST", "/api/programs/recommend", None),
    ("Workout Builder", "POST", "/api/workouts/build",
     {"picks": {"legs": 2, "core": 2}, "time_budget_minutes": 25, "equipment": ["mat", "resistance_band"]}),
    ("Coach", "GET", "/api/coach/summary", None),
    ("Workout Basics", "POST", "/api/basics/ask", {"question": "How long should I rest between sets?"}),
    ("Workout Basics (red flag)", "POST", "/api/basics/ask",
     {"question": "I get a sharp pain in my lower back when I do glute bridges. Should I push through?"}),
]


def main() -> None:
    keep = "--keep" in sys.argv
    transcript = {"ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "calls": []}
    with TestClient(app) as client:
        username = f"demo.{int(time.time())}"
        r = client.post("/api/users", json={"username": username, "first_name": "Demo",
                                            "password": "demo-password-123"})
        uid, token = r.json()["user_id"], r.json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        client.put(f"/api/users/{uid}/quiz-profile", headers=h, json={
            "consent_accepted": True, "consent_version": "2026-10-22",
            "answers": {"goal": "lose_weight", "experience_level": "beginner",
                        "equipment": ["bodyweight", "mat", "resistance_band"], "injuries": ["lower_back"],
                        "pregnancy_status": "none", "weight": 165, "goal_weight": 155}})
        today = datetime.now(timezone.utc).date()
        conn = connect()
        with conn:
            for d in range(11):   # 11 days in a row, to show the overtraining flag
                day = (today - timedelta(days=d)).isoformat()
                conn.execute("INSERT INTO workout_logs (user_id, date, exercise_id, sets, reps, weight_used) "
                             "VALUES (?, ?, 'band_seated_row', 3, 12, 15)", (uid, day))
                conn.execute("INSERT INTO workout_logs (user_id, date, exercise_id, sets, reps) "
                             "VALUES (?, ?, 'bird_dog', 3, 8)", (uid, day))
            for d, w in ((20, 167.5), (0, 165.0)):
                conn.execute("INSERT INTO measurements (user_id, date, body_weight) VALUES (?, ?, ?)",
                             (uid, (today - timedelta(days=d)).isoformat(), w))
        conn.close()
        print(f"Demo user {uid} ({username}): goal lose_weight, injury lower_back, 11-day streak.\n")

        for label, method, route, body in CALLS:
            started = time.perf_counter()
            r = client.request(method, route, json=body, headers=h)
            secs = time.perf_counter() - started
            data = r.json()
            transcript["calls"].append({"agent": label, "request": f"{method} {route}", "body": body,
                                        "status": r.status_code, "seconds": round(secs, 1), "response": data})
            print("=" * 100)
            print(f"{label}: {method} {route}  ->  HTTP {r.status_code} in {secs:.1f}s")
            if body:
                print("body:", json.dumps(body))
            meta = data.get("meta", {})
            for c in meta.get("tool_calls", []):
                print(f"  tool call ({c['called_by']}): {c['tool']}({json.dumps(c['args'])})")
            if "usage" in meta:
                print("  usage:", json.dumps(meta["usage"]))
            print(json.dumps(data.get("result", data), indent=2)[:2500])

        print("=" * 100)
        runs = [dict(r) for r in connect().execute(
            "SELECT id, agent_name, user_id, input_tokens, output_tokens, cached_tokens, requests, tool_calls, "
            "route, status, duration_ms, timestamp FROM agent_runs WHERE user_id = ? ORDER BY id", (uid,))]
        events = [dict(r) for r in connect().execute("SELECT * FROM safety_events WHERE user_id = ?", (uid,))]
        transcript.update(agent_runs=runs, safety_events=events)
        print("agent_runs rows for this demo:")
        for row in runs:
            print("  ", json.dumps(row))
        print("safety_events rows for this demo:")
        for row in events:
            print("  ", json.dumps(row))

        if not keep:
            d = client.delete(f"/api/users/{uid}", headers=h).json()
            transcript["cleanup"] = d
            print("\nDemo account deleted:", json.dumps(d))
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(transcript, indent=2), encoding="utf-8")
    print(f"Transcript written to {OUT.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()

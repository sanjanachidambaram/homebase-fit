"""ONE-TIME content generation: AI-drafted injury cautions for the imported free-exercise-db exercises.

Run from backend/ (needs PORTKEY_API_KEY, like the agents; resumable: exercises already drafted are skipped):
    .venv\\Scripts\\python.exe -m app.db.draft_injury_tags              everything not drafted yet
    .venv\\Scripts\\python.exe -m app.db.draft_injury_tags --limit 12   a small trial
    .venv\\Scripts\\python.exe -m app.db.draft_injury_tags --recheck "<name regex>" --note "<what to re-check>"
        re-drafts the exercises whose name matches, with a note (used once, 2026-10-24, for moves that bring the bar
        behind or to the neck: the first pass had missed a neck caution there). Same rules, same log.
Then rebuild the database (python -m app.db.seed) and the PT template (python -m app.db.export_tag_template).

This is not a live agent: no user, no user data, nothing at request time. It drafts the same thing the hand-authored
exercises carry (content/exercises/*/exercises.yaml): for each injury area in app.safety_rules.INJURY_FLAGS, either
no caution or a caution with a short, general, biomechanical reason. The rules are the same, no exceptions:
  * tier "ai_drafted", source "Pending review by a licensed physical therapist", on every entry;
  * the reason never looks like a citation (safety_rules.RATIONALE_CITATION_LIKE: no years, journals, "et al",
    DOIs, "research", "studies show"), checked here, again by the seed, and by tests/test_injury_rationale.py;
  * an area is flagged only where a caution is plausible: no forced coverage.
A draft that breaks a rule is sent back once with the problem; if it still fails, that exercise stays untagged
(so it stays out of injured users' plans, exactly as before) and is listed under "failed".

Cost: one model call covers BATCH_SIZE exercises and all injury areas at once (prompt: prompts/injury_tag_drafter.md).
Every call's tokens go to injury_tags_generation_log.csv next to the output, NOT to agent_runs (which records live,
user-facing agent calls for the tokenomics report); the totals are in the output file's "generation" block.
"""

import asyncio
import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.usage import RunUsage

from app.agents.harness import MODEL_SETTINGS, _requests, get_model, load_prompt, summarize_gateway
from app.config import CONTENT_DIR, MODEL_NAME, PROMPTS_DIR
from app.safety_rules import INJURY_FLAGS, RATIONALE_CITATION_LIKE, RATIONALE_PENDING_SOURCE

FEDB_DIR = CONTENT_DIR / "exercises" / "source_free_exercise_db"
OUT = FEDB_DIR / "injury_tags_ai_drafted.json"
LOG = FEDB_DIR / "injury_tags_generation_log.csv"
PROMPT = "injury_tag_drafter"
BATCH_SIZE = 6
CONCURRENCY = 4
INSTRUCTIONS_MAX = 700           # characters of the dataset's instructions shown per exercise
REASON_MIN, REASON_MAX = 40, 360
LOG_FIELDS = ("started_at", "batch", "attempt", "exercise_ids", "model", "requests", "input_tokens", "output_tokens",
              "total_tokens", "gateway_cache_status", "seconds", "status", "note")

Injury = Literal["neck", "shoulder", "upper_back", "lower_back", "wrist", "hip", "knee", "ankle"]
assert set(Injury.__args__) == set(INJURY_FLAGS), "Injury must match safety_rules.INJURY_FLAGS"


class Caution(BaseModel):
    injury: Injury
    reasoning: str = Field(description="one or two plain sentences, 15-45 words, no citations")


class ExerciseDraft(BaseModel):
    exercise_id: str
    cautions: list[Caution] = Field(description="only the areas with a plausible caution; may be empty")


class BatchDraft(BaseModel):
    results: list[ExerciseDraft]


drafter = Agent(output_type=BatchDraft, instructions=load_prompt(PROMPT), name="injury_tag_drafter")


def describe(ex: dict) -> dict:
    text = " ".join(s.strip() for s in ex.get("instructions", []))
    return {"exercise_id": ex["id"], "name": ex["name"], "category": ex.get("category"),
            "equipment": ex.get("equipment"), "force": ex.get("force"), "mechanic": ex.get("mechanic"),
            "level": ex.get("level"), "primary_muscles": ex.get("primaryMuscles", []),
            "secondary_muscles": ex.get("secondaryMuscles", []),
            "instructions": text[:INSTRUCTIONS_MAX] + ("..." if len(text) > INSTRUCTIONS_MAX else "")}


def problems(draft: ExerciseDraft) -> list[str]:
    """Every rule the stored data must meet, checked before anything is kept."""
    out = []
    seen = [c.injury for c in draft.cautions]
    if len(seen) != len(set(seen)):
        out.append("each injury area at most once")
    for c in draft.cautions:
        r = c.reasoning.strip()
        if not REASON_MIN <= len(r) <= REASON_MAX:
            out.append(f"{c.injury}: the reason must be {REASON_MIN}-{REASON_MAX} characters")
        if RATIONALE_CITATION_LIKE.search(r):
            out.append(f"{c.injury}: no citations, years, journals, 'research' or 'studies show'")
    return out


def stored(draft: ExerciseDraft, now: str) -> dict:
    cautions = sorted(draft.cautions, key=lambda c: INJURY_FLAGS.index(c.injury))
    return {"injury_contraindications": [c.injury for c in cautions],
            "injury_rationale": {c.injury: {"reasoning": c.reasoning.strip(), "tier": "ai_drafted",
                                            "source": RATIONALE_PENDING_SOURCE} for c in cautions},
            "generated_at": now}


def load_out() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"about": ("AI-drafted injury cautions for the imported free-exercise-db exercises (one-time content "
                      "generation, app/db/draft_injury_tags.py). Every entry is tier ai_drafted, pending review by a "
                      "licensed physical therapist. The seed loads these; see content/exercises/README.md."),
            "generation": {}, "drafts": {}, "failed": {}}


def save_out(data: dict) -> None:
    data["drafts"] = dict(sorted(data["drafts"].items()))
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def log_row(row: dict) -> None:
    new = not LOG.exists()
    with LOG.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow(row)


async def call(batch_no: int, attempt: int, exercises: list[dict], note: str = "") -> tuple[BatchDraft | None, dict]:
    usage, calls = RunUsage(), []
    token = _requests.set(calls)
    started, stamp = time.perf_counter(), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prompt = ("Draft injury cautions for these exercises:\n" + json.dumps([describe(e) for e in exercises], indent=1)
              + (f"\n\nYour previous draft broke these rules, fix them: {note}" if note else ""))
    out, status = None, "ok"
    try:
        out = (await drafter.run(prompt, model=get_model(), usage=usage, model_settings=MODEL_SETTINGS)).output
    except Exception as exc:   # logged with whatever tokens were used, then the exercises stay untagged
        status = f"error: {type(exc).__name__}"
    finally:
        _requests.reset(token)
    gateway = summarize_gateway(calls)
    row = {"started_at": stamp, "batch": batch_no, "attempt": attempt,
           "exercise_ids": ";".join(e["id"] for e in exercises), "model": MODEL_NAME, "requests": usage.requests,
           "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
           "total_tokens": usage.input_tokens + usage.output_tokens,
           "gateway_cache_status": gateway["gateway_cache_status"],
           "seconds": round(time.perf_counter() - started, 1), "status": status, "note": note[:200]}
    log_row(row)
    return out, row


async def run_batch(batch_no: int, exercises: list[dict], data: dict, lock: asyncio.Lock, sem: asyncio.Semaphore):
    async with sem:
        out, _ = await call(batch_no, 1, exercises)
        by_id = {d.exercise_id: d for d in out.results} if out else {}
        retry = []
        for ex in exercises:
            d = by_id.get(ex["id"])
            issue = "no result for this exercise" if d is None else "; ".join(problems(d))
            if issue:
                retry.append((ex, issue))
            else:
                async with lock:
                    data["drafts"][ex["id"]] = stored(d, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        for ex, issue in retry:   # one more try each, with the problem spelled out
            out, _ = await call(batch_no, 2, [ex], issue)
            d = next((x for x in out.results if x.exercise_id == ex["id"]), None) if out else None
            again = "no result" if d is None else "; ".join(problems(d))
            async with lock:
                if again:
                    data["failed"][ex["id"]] = again
                else:
                    data["drafts"][ex["id"]] = stored(d, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
                    data["failed"].pop(ex["id"], None)
        async with lock:
            save_out(data)   # after every batch, so an interrupted run loses nothing
            print(f"batch {batch_no}: {len(data['drafts'])} drafted, {len(data['failed'])} failed", flush=True)


def totals() -> dict:
    rows = list(csv.DictReader(LOG.open(encoding="utf-8"))) if LOG.exists() else []
    n = lambda k: sum(int(r[k] or 0) for r in rows)
    return {"model": MODEL_NAME, "calls": len(rows), "requests": n("requests"), "input_tokens": n("input_tokens"),
            "output_tokens": n("output_tokens"), "total_tokens": n("total_tokens"),
            "errors": sum(1 for r in rows if r["status"] != "ok"), "log": LOG.name}


async def recheck(pattern: str, note: str) -> None:
    """Re-draft the exercises whose name matches `pattern`, one call each, with `note` as the thing to re-check. The
    model still decides; the result replaces the old draft only if it passes every rule."""
    import re
    library = json.loads((FEDB_DIR / "exercises.json").read_text(encoding="utf-8"))
    data = load_out()
    batch = max([int(r["batch"]) for r in csv.DictReader(LOG.open(encoding="utf-8"))], default=0) + 1
    for ex in [e for e in library if re.search(pattern, e["name"], re.I)]:
        out, _ = await call(batch, 1, [ex], f"Re-check this exercise: {note}")
        d = next((x for x in out.results if x.exercise_id == ex["id"]), None) if out else None
        if d is not None and not problems(d):
            before = data["drafts"].get(ex["id"], {}).get("injury_contraindications")
            data["drafts"][ex["id"]] = stored(d, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            print(f"{ex['name']}: {before} -> {data['drafts'][ex['id']]['injury_contraindications']}")
        else:
            print(f"{ex['name']}: kept the earlier draft (the re-check didn't pass the rules)")
        batch += 1
    data["generation"].update({**totals(), "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "rechecks": data["generation"].get("rechecks", []) + [{"pattern": pattern, "note": note}]})
    save_out(data)
    print(json.dumps({k: data["generation"][k] for k in ("calls", "input_tokens", "output_tokens", "total_tokens")}))


async def main(limit: int | None) -> None:
    library = json.loads((FEDB_DIR / "exercises.json").read_text(encoding="utf-8"))
    data = load_out()
    todo = [e for e in library if e["id"] not in data["drafts"]][:limit]
    print(f"{len(todo)} exercises to draft in batches of {BATCH_SIZE} ({len(data['drafts'])} already drafted)")
    lock, sem = asyncio.Lock(), asyncio.Semaphore(CONCURRENCY)
    first = max([int(r["batch"]) for r in csv.DictReader(LOG.open(encoding="utf-8"))], default=0) + 1 \
        if LOG.exists() else 1
    batches = [todo[i:i + BATCH_SIZE] for i in range(0, len(todo), BATCH_SIZE)]
    await asyncio.gather(*(run_batch(first + i, b, data, lock, sem) for i, b in enumerate(batches)))
    prompt_text = (PROMPTS_DIR / f"{PROMPT}.md").read_text(encoding="utf-8")
    data["generation"] = {**totals(), "prompt": f"backend/prompts/{PROMPT}.md",
                          "prompt_sha256": hashlib.sha256(prompt_text.encode()).hexdigest(),
                          "batch_size": BATCH_SIZE, "exercises_drafted": len(data["drafts"]),
                          "exercises_failed": len(data["failed"]),
                          "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    save_out(data)
    print(json.dumps(data["generation"], indent=1))


if __name__ == "__main__":
    if "--recheck" in sys.argv:
        asyncio.run(recheck(sys.argv[sys.argv.index("--recheck") + 1], sys.argv[sys.argv.index("--note") + 1]))
    else:
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        asyncio.run(main(lim))

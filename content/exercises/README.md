# Exercises

Two sources feed the `exercises` table (see `content/sources.yaml`):

| Folder | `source_dataset` | Injury tags |
|---|---|---|
| `legs/`, `arms/`, `chest/`, `shoulders/`, `back/`, `core/`, `full_body/` (`exercises.yaml` in each) | `placeholder-authored` | drafted, not yet PT-reviewed (`draft`) |
| `source_free_exercise_db/` (see its `ATTRIBUTION.md`) | `free-exercise-db` | AI-drafted in bulk, not yet PT-reviewed (`draft`; see below) |

> **Heads-up for PT review: the workload just went from 27 exercises to 903.** On 2026-10-24 all 876 imported
> free-exercise-db exercises were given AI-drafted injury cautions in one batch. Together with the 27 hand-authored
> ones, all 903 exercises now carry drafted injury data: 860 have at least one caution (2,265 cautions in all, each
> with its own reason) and 43 were judged to need none. **Every one of them is `ai_drafted` and still needs a
> licensed physical therapist's review.** It's fine to review in batches (for example, the exercises the plans
> actually use first); the template below lists them all.

For anyone with an injury flag, generated plans and custom workouts only use exercises that have drafted injury
tags. Since the bulk drafting, that is the whole library, so injured users' plans can now include imported exercises
whose cautions are AI drafts (before, only the 27 hand-authored ones qualified). The tags cover neck, shoulder,
upper_back, lower_back, wrist, hip, knee and ankle; the wrist and ankle tags were drafted 2026-10-22, neck, upper_back
and hip on 2026-10-23, the imported library on 2026-10-24, and like the rest they are waiting on PT review. Every
drafted exercise has been considered for every one of these, so a new injury flag has to be drafted across all of
them (the hand-authored YAML and the bulk drafts), not just added to the quiz.

Every exercise starts as `status: placeholder` with no citations, so the app shows "Content pending expert review" on it. For hand-authored exercises you can add `status: pt_reviewed` and a `citations:` list (each `{claim, source}`) in `exercises.yaml`; `pt_reviewed` requires at least one citation. Demo media type (image, gif, or video) is picked from the file extension when you rerun the seed.

## Injury tagging for the PT

`contraindication_tags_TEMPLATE.csv` lists **every** exercise from both sources, one row each.

1. Save a copy as `contraindication_tags.csv` and fill that in. The template gets regenerated, so edits made to it directly would be lost.
2. In `neck`, `shoulder`, `upper_back`, `lower_back`, `wrist`, `hip`, `knee`, `ankle`: `Y` = unsafe for someone with that injury, `N` = OK, blank = not reviewed.
3. `rationale` says **why** each `Y` is there, one `injury: reasoning` per line. Every one is pre-filled with
   AI-drafted reasoning (`rationale_tier` = `ai_drafted`): general exercise-science reasoning, with no citation
   behind it. Confirm it, correct it in place, or replace it; add a reason for any new `Y` you add.
4. Add your name and credentials in `reviewed_by` for each row you've checked; use `pt_notes` for anything else.
   Once you've reviewed a row, its rationale becomes `tier: pt_reviewed` with your name and credentials as the
   `source` (in that exercise's `injury_rationale` in `exercises.yaml`).

### Injury rationale in `exercises.yaml`

Each injury tag on a hand-authored exercise has a matching `injury_rationale` entry:

```yaml
injury_contraindications: [knee]
injury_rationale:
  knee:
    reasoning: "Squatting bends the knees while they carry your body weight, ..."
    tier: ai_drafted          # ai_drafted until a PT confirms it, then pt_reviewed
    source: Pending review by a licensed physical therapist   # then: the PT's name and credentials
```

The seed refuses to build if a tag has no rationale (or a rationale has no tag), if `tier` is anything else, or if
a `pt_reviewed` entry still says "Pending review". The app shows this reasoning in the exercise detail view and,
for people with an injury flag, in the "left out for your injury" list on their plan, always with its review tier.

### The bulk AI drafts (`source_free_exercise_db/injury_tags_ai_drafted.json`)

Written once by `backend/app/db/draft_injury_tags.py` with gpt-6-luna (prompt: `backend/prompts/injury_tag_drafter.md`),
6 exercises and all 8 injury areas per call. Same rules as the hand-authored drafts: tier `ai_drafted`, source
"Pending review by a licensed physical therapist", general biomechanical reasoning with nothing that looks like a
citation (checked by the generator, the seed and the tests), and a caution only where one is plausible. To correct
one, edit its entry in that file (or move the exercise's review into the CSV as below) and rerun the seed. The token
cost of the run is in `injury_tags_generation_log.csv` (one row per call) and the file's `generation` block:
546,613 tokens over 153 calls (349,598 in, 197,015 out): 146 batch calls, 3 retries (two drafts had used wording
the citation guard rejects, one exercise was missing from its batch's answer; all three passed on the retry), and 4
re-checks of moves that bring the bar behind or to the neck (6,292 tokens; the first pass had missed a neck caution on
"Push Press - Behind the Neck"). It is a one-time content cost, kept apart from `agent_runs` (live, user-facing agent
calls).

Regenerate the template after changing exercises (from `backend/`):

```bash
.venv\Scripts\python.exe -m app.db.export_tag_template
```

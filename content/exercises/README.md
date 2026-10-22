# Exercises

Two sources feed the `exercises` table (see `content/sources.yaml`):

| Folder | `source_dataset` | Injury tags |
|---|---|---|
| `legs/`, `arms/`, `chest/`, `shoulders/`, `back/`, `core/`, `full_body/` (`exercises.yaml` in each) | `placeholder-authored` | drafted, not yet PT-reviewed (`draft`) |
| `source_free_exercise_db/` (see its `ATTRIBUTION.md`) | `free-exercise-db` | none yet (`untagged`) |

Program templates can only use the hand-authored exercises for now, because those are the only ones with injury tags.

Every exercise starts as `status: placeholder` with no citations, so the app shows "Content pending expert review" on it. For hand-authored exercises you can add `status: pt_reviewed` and a `citations:` list (each `{claim, source}`) in `exercises.yaml`; `pt_reviewed` requires at least one citation. Demo media type (image, gif, or video) is picked from the file extension when you rerun the seed.

## Injury tagging for the PT

`contraindication_tags_TEMPLATE.csv` lists **every** exercise from both sources, one row each.

1. Save a copy as `contraindication_tags.csv` and fill that in. The template gets regenerated, so edits made to it directly would be lost.
2. In `lower_back`, `knee`, `shoulder`: `Y` = unsafe for someone with that injury, `N` = OK, blank = not reviewed.
3. Add your name in `reviewed_by` for each row you've checked; use `pt_notes` for anything else.

Regenerate the template after changing exercises (from `backend/`):

```bash
.venv\Scripts\python.exe -m app.db.export_tag_template
```

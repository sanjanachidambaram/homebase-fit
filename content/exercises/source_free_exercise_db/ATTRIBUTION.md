# Attribution: Free Exercise DB

The exercise library and demo images in this folder come from:

- **Dataset:** Free Exercise DB (free-exercise-db) by Yuhonas
- **URL:** https://github.com/yuhonas/free-exercise-db
- **License:** The Unlicense (public domain). See https://github.com/yuhonas/free-exercise-db/blob/main/LICENSE.md
- **Version used:** commit `f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5` (also in `SOURCE_COMMIT`), fetched 2026-10-22
- **Upstream origin:** free-exercise-db restructures the [exercises.json](https://github.com/wrkout/exercises.json) dataset by Ollie Jennings.

## What's here

| Path | Contents |
|---|---|
| `exercises.json` | The dataset's `dist/exercises.json`, unmodified (876 exercises) |
| `images/<id>/<n>.jpg` | The dataset's demo images, unmodified (1,746 files) |
| `SOURCE_COMMIT` | The upstream commit these files were taken from |

## How HomeBase Fit uses it

`backend/app/db/seed.py` imports every exercise into the `exercises` table with
`source_dataset = 'free-exercise-db'`. It maps the dataset's muscles, equipment,
and level onto HomeBase Fit's own categories; the original `primaryMuscles` and
`secondaryMuscles` are kept alongside.

**Injury tags:** the dataset has no injury information. Every imported exercise starts
with `contraindication_status = 'untagged'` until a PT tags it in
`content/exercises/contraindication_tags_TEMPLATE.csv`.

The Unlicense doesn't require attribution, but we credit the dataset anyway, in this
file and on the site's "Data & Sources" footer (served from `GET /api/sources`).

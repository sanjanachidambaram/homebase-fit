# back exercises: demo media

The exercises in this group are defined in `exercises.yaml` in this folder.

Put demo media here, named exactly after the exercise `id`:

- image: `<id>.jpg` or `<id>.png`
- animation: `<id>.gif`
- short video: `<id>.mp4` (H.264, a few seconds, muted, under 5 MB)

Example: the demo for `bird_dog` goes here as `bird_dog.gif`.

After adding files, rerun the seed from `backend/` so the database picks up the real file names:

```bash
.venv\Scripts\python.exe -m app.db.seed
```

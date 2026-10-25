# Bee Fit

(Formerly HomeBase Fit, renamed 2026-10-25. The Render service is now `bee-fit`. Internal names keep `homebase` on
purpose: the database files `homebase.db` / `homebase_original.db`, `HOMEBASE_DB_PATH`, the GitHub repo, the MCP server
id and the browser's saved sign-in key. Renaming those would detach the database and sign everyone out.)

A home workout coach for limited equipment that plans around your goals and your injuries at the same time.
Class project: not a substitute for professional medical advice.

## Run it locally

You need Python 3.11+ and Node 20+. Put `PORTKEY_API_KEY` (and optionally `APP_SECRET_KEY`) in a `.env` file in this
folder or the folder above it; see `.env.example`.

One-time setup:

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
cd ../frontend
npm install
```

Then, in two terminals:

```bash
cd backend
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8000
```

```bash
cd frontend
npm run dev
```

Open http://localhost:5173, create an account, take the quiz, and you'll land on the Dashboard.

Tests: `cd backend` then `.venv/Scripts/python.exe -m pytest`.

More: `design.md` (visual direction), `backend/prompts/shared_rules.md` (agent rules),
`backend/app/mcp_server/README.md` (the MCP tools).

## Deployment (Render, paid instance with a persistent disk)

The whole app runs as **one** Render web service, `bee-fit`: FastAPI serves the API (`/api/*`), the media in `content/`
(`/content/*`), and the built React app (every other path). The setup is in [`render.yaml`](render.yaml); Python 3.13
and Node 24 are pinned by `.python-version` and `.node-version`.

**The live site runs on a paid Render instance (`starter`) with a 1 GB persistent disk, so people's accounts and
data survive redeploys.** This is a deliberate cost tradeoff for reliability. On the free tier the container's
filesystem is wiped on every deploy and restart, so every account, calendar and log disappeared between visits; a
persistent disk is only available on paid instances. Check Render's pricing page for the current cost of the
instance and the disk. (A side benefit: paid instances don't sleep, so there's no slow first visit.)

How the data is kept:
- The working database lives on the disk at `/var/data/homebase.db` (`HOMEBASE_DB_PATH`, set in `render.yaml`). Only
  the disk persists; the code, content and exercise images come from git with each deploy.
- **First use of an empty disk:** the app builds the working database from the clean
  `backend/app/db/homebase_original.db`, exactly as it always has, just on the disk.
- **Normal redeploys:** the database on the disk is left alone.
- **A deploy with new content or a new schema** (a changed `homebase_original.db`): on startup the app copies the
  database to `/var/data/homebase.before-refresh-<time>.db` (it keeps the last 3), then refreshes it with the same
  account-keeping refresh as `python -m app.db.seed`, so the code and the schema always match and nobody loses their
  account. The startup log says which of the three happened (`Working database ...: created / unchanged /
  refreshed`).
- Render also takes a daily snapshot of the disk (kept for at least 7 days).
- Limits that come with a disk: one instance only, and no zero-downtime deploys (each deploy has a few seconds of
  downtime while the new version starts).

Local development is unchanged: without `HOMEBASE_DB_PATH`, the working database is `backend/app/db/homebase.db`.

**Secrets never go in the repo.** Render asks for them once, in its dashboard (step 4). In production
(`APP_ENV=production`) the app reads only real environment variables and ignores any `.env` file.

### Steps only you can do (on render.com)

1. **Create an account.** Go to https://render.com, click **Get Started**, and sign up with **GitHub** (easiest, since
   Render then sees your repos).
2. **Start a Blueprint.** In the Render dashboard click **New +** (top right) → **Blueprint**.
3. **Connect the repo.** Click **Connect GitHub** if asked, and in the GitHub window give Render access to the
   `homebase-fit` repository (for a private repo, choose "Only select repositories" and pick it). Back in Render,
   select `homebase-fit` and click **Connect**. Render reads `render.yaml` and shows one web service,
   `bee-fit`, on the **Starter** plan with a disk `bee-fit-data` at `/var/data`. Give the Blueprint any name.
4. **Enter the environment variables** Render asks for (`PUBLIC_BASE_URL` and `HOMEBASE_DB_PATH` are already set by
   `render.yaml`):
   - `APP_ENV` = `production`
   - `APP_SECRET_KEY` = a long random string. Make one on your computer with
     `python -c "import secrets; print(secrets.token_hex(32))"` and paste the output. (It signs sign-in tokens;
     don't reuse it anywhere else.)
   - `PORTKEY_API_KEY` = your course Portkey key (the same value as in your local `.env`).
   - `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`:
     declared for later, but **the app doesn't read them yet** (it has its own sign-in and keeps its data in SQLite at
     `HOMEBASE_DB_PATH`). Leave them blank unless code that uses them is added.

   Do **not** add `OPENAI_API_KEY`. Render only asks for these once; to change one later, open the service →
   **Environment** → edit → **Save Changes** (it redeploys).
5. **Deploy.** Click **Apply** (or **Deploy Blueprint**). The first build takes about 5 minutes: it installs the
   Python packages, then runs `npm ci` and `npm run build`. Click into the `bee-fit` service → **Logs** to watch.
   It's done when the status at the top says **Live** (and the log shows `Uvicorn running`).
6. **Find the live URL.** It's at the top of the `bee-fit` service page, under the name:
   `https://bee-fit.onrender.com` (if Render had to add a few characters because the name was taken, change
   `PUBLIC_BASE_URL` in `render.yaml` to match). Open it and check:
   - `https://<your-url>/api/health` shows `"status":"ok"` and `"llm_provider":"portkey"`.
   - The home page loads; sign up, take the quiz, and your plan and calendar appear.

After this, every `git push` to `main` redeploys automatically, and accounts and data stay on the disk.

### Moving from the old `homebase-fit` service to `bee-fit` (2026-10-25)

`bee-fit` is a **new** service with its own **new, empty** disk, so it starts with no accounts: the database on the
old `homebase-fit` disk does not move by itself. The old service also keeps running (and billing) until you suspend or
delete it; removing it from `render.yaml` doesn't delete it. To keep everyone's accounts:
1. Deploy `bee-fit` from the Blueprint, but don't share the new URL yet.
2. Copy `/var/data/homebase.db` from the old service's disk to the new one (Render's SSH / SCP for paid services, from
   each service's **Shell** or **Connect** menu), into `/var/data/homebase.db` on `bee-fit`, then restart `bee-fit`.
   The startup log should say `Working database /var/data/homebase.db: unchanged` (or `refreshed`), not `created`.
3. Check that an existing account can sign in on `bee-fit`, then suspend or delete `homebase-fit`.
Sign-in tokens are signed with `APP_SECRET_KEY`: use the same value on `bee-fit` so people stay signed in, or a new
one to sign everyone out once.

### Moving an existing free service to the paid plan with a disk

If the service was first created on the free tier: open the `bee-fit` service → **Settings** → **Instance Type**
→ choose **Starter** → **Save**. Then **Disks** (left sidebar) → **Add Disk**: name `bee-fit-data`, mount path
`/var/data`, size `1` GB → **Save**. Then **Environment** → add `HOMEBASE_DB_PATH` = `/var/data/homebase.db` (a Blueprint
sync also adds it from `render.yaml`). Render redeploys; the startup log shows `Working database /var/data/homebase.db:
created`, and from then on accounts survive redeploys. Data from the free-tier days is not carried over (it was never
kept). If a deploy
fails, the **Logs** tab shows the error; the build log is in the **Events** tab under that deploy.

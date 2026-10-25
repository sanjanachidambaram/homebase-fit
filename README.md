# Bee Fit

(Formerly HomeBase Fit, renamed 2026-10-25. The Render service is now `bee-fit`. Internal names keep `homebase` on
purpose: the GitHub repo, the MCP server id and the browser's saved sign-in key. Renaming those would break links and
sign everyone out.)

A home workout coach for limited equipment that plans around your goals and your injuries at the same time.
Class project: not a substitute for professional medical advice.

## Run it locally

You need Python 3.11+, Node 20+ and a Postgres database. Put `DATABASE_URL` and `PORTKEY_API_KEY` (and optionally
`APP_SECRET_KEY`) in a `.env` file in this folder or the folder above it; see `.env.example`. The easiest database is a
second, free Neon **branch** of the production project (Neon → **Branches → New branch**, then **Connect**): it's a
separate copy, so local testing never touches live accounts. The app creates the tables and loads the content on its
first start.

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

Tests: `cd backend` then `.venv/Scripts/python.exe -m pytest`. They never use `DATABASE_URL`: each test gets its own
throwaway Postgres database. On Windows, download a portable PostgreSQL once with
`.venv/Scripts/python.exe scripts/get_test_postgres.py` (about 300 MB into `backend/.pg`, gitignored; nothing is
installed) and the tests start and stop it themselves. Elsewhere, set `TEST_DATABASE_ADMIN_URL` to a Postgres server the
tests may create databases on.

More: `design.md` (visual direction), `backend/prompts/shared_rules.md` (agent rules),
`backend/app/mcp_server/README.md` (the MCP tools).

## Deployment (Render free plan + a free Neon Postgres database)

The whole app runs as **one** Render web service, `bee-fit`: FastAPI serves the API (`/api/*`), the media in `content/`
(`/content/*`), and the built React app (every other path). The setup is in [`render.yaml`](render.yaml); Python 3.13
and Node 24 are pinned by `.python-version` and `.node-version`.

**No disk, no SQLite, free plan.** Every account and all user data live in a Postgres database at `DATABASE_URL` (a free
[Neon](https://neon.tech) project). The service keeps nothing on its own filesystem, so it runs on Render's **free**
plan with no persistent disk: a redeploy or restart loses nothing. (Until 2026-10-25 the data was a SQLite file on a
paid instance's disk; that's gone.) Free-plan tradeoff: the service sleeps after about 15 minutes without visits, so
the first visit after that takes up to a minute; Neon's free database also pauses when idle and wakes in about a second.

How the database is kept up to date (on every start, `backend/app/db/__init__.py: ensure_database`):
- **The schema** comes from the Alembic migrations in `backend/migrations` (`alembic upgrade head`, run automatically).
  A schema change is a new migration file; nothing is ever rebuilt from a copied database file.
- **The content** (exercises, quiz questions, protocols, sources) is loaded from `content/` the first time, and again
  only when a deploy ships changed content files. Accounts and user data are never touched by it. The startup log
  says `Database: schema up to date, content seeded / unchanged / refreshed`.
- **Backups:** Neon can restore the database to an earlier point in time (the free plan keeps a short history; see
  Neon's plans page).

**Required environment variables** (all read by the code; secrets never go in the repo, and Render asks for each one
once, in its dashboard). In production (`APP_ENV=production`) the app reads only real environment variables and ignores
any `.env` file.

| Variable | What it is |
| --- | --- |
| `DATABASE_URL` | **Required.** The Neon connection string. Without it the app won't start. |
| `APP_ENV` | `production` |
| `APP_SECRET_KEY` | **Required.** A long random string; signs sign-in tokens and the Google / Microsoft sign-in cookie. |
| `PUBLIC_BASE_URL` | Set in `render.yaml` (`https://bee-fit.onrender.com`). The OAuth redirect addresses are built from it. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | **Required for "Continue with Google"** (the button is hidden without them). |
| `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` | **Required for "Continue with Microsoft"** (hidden without them). |
| `PORTKEY_API_KEY` | The course Portkey key (blank = AI features off). Do **not** add `OPENAI_API_KEY`. |

Sign-in: username and password (Argon2-hashed; accounts with older hashes are upgraded the next time they sign in),
or Google / Microsoft (OpenID Connect with PKCE, state and nonce: `backend/app/oauth.py`). Sign-in, sign-up and the
OAuth routes are rate limited per IP address. A Google / Microsoft sign-in joins an existing account only when the
provider confirms the email address is verified and an account already has that verified address; otherwise it makes a
new account.

### Steps only you can do

**1. Create the Neon database (free).**
1. Go to https://neon.tech → **Sign up** (GitHub works) → **Create project**. Name it `bee-fit`, Postgres **17**, and
   pick the region closest to your Render region (e.g. *AWS US East (Ohio)* for Render's Ohio, *US West (Oregon)* for
   Oregon).
2. On the project dashboard click **Connect**. Leave **Connection pooling** on, copy the connection string (it looks
   like `postgresql://neondb_owner:...@ep-...-pooler.<region>.aws.neon.tech/neondb?sslmode=require`). That whole string
   is `DATABASE_URL`. Treat it like a password.

**2. Create the Google sign-in app.**
1. https://console.cloud.google.com → create a project (e.g. `Bee Fit`).
2. **APIs & Services → OAuth consent screen**: User type **External**, app name `Bee Fit`, your email as support and
   developer contact. Scopes: `openid`, `email`, `profile` (nothing else). Then **Publish app** (while it says
   *Testing*, only the test users you list can sign in).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**: type **Web application**. Under
   **Authorized redirect URIs** add exactly `https://bee-fit.onrender.com/api/auth/google/callback` (and, for local
   testing, `http://localhost:8000/api/auth/google/callback`). **Create**, then copy the **Client ID** and **Client
   secret**.

**3. Create the Microsoft sign-in app.**
1. https://portal.azure.com → **Microsoft Entra ID → App registrations → New registration**. Name `Bee Fit`.
   Supported account types: **Accounts in any organizational directory and personal Microsoft accounts**. Redirect URI:
   platform **Web**, `https://bee-fit.onrender.com/api/auth/microsoft/callback`. **Register**.
2. Copy the **Application (client) ID** from the **Overview** page.
3. **Certificates & secrets → New client secret** → copy its **Value** right away (it's shown once; note when it
   expires and make a new one before then).
4. (Optional, for local testing) **Authentication → Add URI**: `http://localhost:8000/api/auth/microsoft/callback`.

**4. Deploy on Render.**
1. https://render.com → **New + → Blueprint** → connect the `homebase-fit` GitHub repo. Render reads `render.yaml` and
   shows one web service, `bee-fit`, on the **Free** plan, with no disk.
2. Enter the variables from the table above (`PUBLIC_BASE_URL` is already filled in). For `APP_SECRET_KEY` run
   `python -c "import secrets; print(secrets.token_hex(32))"` and paste the output; if you're moving accounts from the
   old service, use **the same value it had**, so people stay signed in.
3. **Apply.** The first build takes about 5 minutes. When the service says **Live**, check:
   - `https://bee-fit.onrender.com/api/health` shows `"status":"ok"`, and the log shows
     `Database: schema up to date, content seeded.`
   - The sign-in form shows **Continue with Google** and **Continue with Microsoft**; both work, and so does a
     username / password account.

To change a variable later: the service → **Environment** → edit → **Save Changes** (it redeploys). Every `git push` to
`main` redeploys automatically; the data is in Neon, so nothing is lost.

### Moving the accounts from the old SQLite database (one time)

The old `homebase-fit` service kept its data in `/var/data/homebase.db` on a paid disk. To bring those accounts across
**before anyone signs up on the new service** (the import refuses to run on a database that already has accounts):
1. Download the file from the old service: its **Connect → SSH** menu shows the address; then
   `scp <service-id>@ssh.<region>.render.com:/var/data/homebase.db .`
2. On your computer, from `backend/`, with the Neon string in `DATABASE_URL` (in `.env` or the terminal):
   `.venv/Scripts/python.exe -m app.db.import_sqlite path/to/homebase.db`. It builds the schema and content, copies every
   account and its data (keeping the ids, so existing sign-ins stay valid with the same `APP_SECRET_KEY`), and prints
   how many rows of each table came across and how many were skipped.
3. Check that an old account signs in on `bee-fit`, then **delete the old `homebase-fit` service and its disk** in
   Render (suspending isn't enough: the disk keeps billing). Delete the downloaded `homebase.db` too; it holds personal
   data.

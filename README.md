# HomeBase Fit

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

## Deployment (Render, free tier)

The whole app runs as **one** Render web service: FastAPI serves the API (`/api/*`), the media in `content/`
(`/content/*`), and the built React app (every other path). The setup is in [`render.yaml`](render.yaml); Python 3.13
and Node 24 are pinned by `.python-version` and `.node-version`.

On the free tier the service sleeps after about 15 minutes without visitors (the next visit takes about a minute to
wake it), and its disk is temporary: on every restart or redeploy the working database starts fresh from the clean
`backend/app/db/homebase_original.db`, so test accounts, calendars and logs are wiped. That's expected for this
class project.

**Secrets never go in the repo.** Render asks for them once, in its dashboard (step 4). In production
(`APP_ENV=production`) the app reads only real environment variables and ignores any `.env` file.

### Steps only you can do (on render.com)

1. **Create an account.** Go to https://render.com, click **Get Started**, and sign up with **GitHub** (easiest, since
   Render then sees your repos).
2. **Start a Blueprint.** In the Render dashboard click **New +** (top right) → **Blueprint**.
3. **Connect the repo.** Click **Connect GitHub** if asked, and in the GitHub window give Render access to the
   `homebase-fit` repository (for a private repo, choose "Only select repositories" and pick it). Back in Render,
   select `homebase-fit` and click **Connect**. Render reads `render.yaml` and shows one web service,
   `homebase-fit`, on the **Free** plan. Give the Blueprint any name.
4. **Enter the three environment variables** Render asks for:
   - `APP_ENV` = `production`
   - `APP_SECRET_KEY` = a long random string. Make one on your computer with
     `python -c "import secrets; print(secrets.token_hex(32))"` and paste the output. (It signs sign-in tokens;
     don't reuse it anywhere else.)
   - `PORTKEY_API_KEY` = your course Portkey key (the same value as in your local `.env`).

   Do **not** add `OPENAI_API_KEY`. Render only asks for these once; to change one later, open the service →
   **Environment** → edit → **Save Changes** (it redeploys).
5. **Deploy.** Click **Apply** (or **Deploy Blueprint**). The first build takes about 5 minutes: it installs the
   Python packages, then runs `npm ci` and `npm run build`. Click into the `homebase-fit` service → **Logs** to watch.
   It's done when the status at the top says **Live** (and the log shows `Uvicorn running`).
6. **Find the live URL.** It's at the top of the `homebase-fit` service page, under the name, like
   `https://homebase-fit.onrender.com` (Render adds a few characters if that name is taken). Open it and check:
   - `https://<your-url>/api/health` shows `"status":"ok"` and `"llm_provider":"portkey"`.
   - The home page loads; sign up, take the quiz, and your plan and calendar appear.

After this, every `git push` to `main` redeploys automatically (and resets the test data, as above). If a deploy
fails, the **Logs** tab shows the error; the build log is in the **Events** tab under that deploy.

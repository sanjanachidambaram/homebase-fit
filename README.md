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

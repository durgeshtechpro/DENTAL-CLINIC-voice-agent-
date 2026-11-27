# ZOFT Voice Agent

Bright Smile Dental front desk. A caller talks, the agent listens, checks or books a slot, looks up the clinic FAQ, and hangs up. Each call is saved with a transcript, tool log, latency, and a cost breakdown.

The live demo today is a **browser call**. A real India phone call is not finished. The reason is in [REPORT.md](REPORT.md). The design note is [DESIGN.md](DESIGN.md).

## Run it locally

You need Python 3.12 and Node.js. Copy `.env.example` to `.env` and fill in the keys. Never commit `.env`.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
pip install -r requirements-api.txt
pip install -r requirements-clinic.txt
```

Open three terminals in the project folder:

```powershell
.\.venv\Scripts\python.exe -m uvicorn clinic.main:app --host 127.0.0.1 --port 8001
.\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe agent\main.py dev
```

The API, clinic, and agent read the root `.env`. Then start the web console:

```powershell
cd web
copy .env.example .env.local
npm install
npm run dev
```

Open http://localhost:3000 and press **Start call**. Past calls are at http://localhost:3000/calls. Put the same `API_BASE_URL` and `API_KEY` in `web/.env.local`. The browser never sees the key.

`CLINIC_BASE_URL` defaults to `http://127.0.0.1:8001`. `API_BASE_URL` defaults to `http://127.0.0.1:8000` for the agent. Leave `DATA_DIR` empty to keep the SQLite files in `api/` and `clinic/`.

## Reports

The scripts do not read `.env` by themselves. Set the two variables in the shell. The API must already be running.

```powershell
$env:API_BASE_URL = "http://127.0.0.1:8000"
$env:API_KEY = "<the API key>"
.\.venv\Scripts\python.exe scripts\latency_report.py
.\.venv\Scripts\python.exe scripts\cost_model.py
.\.venv\Scripts\python.exe scripts\export_calls.py
```

`latency_report.py` writes `data/latency-report.md`. `cost_model.py` writes `data/cost-model.md`. `export_calls.py` writes one JSON file per call under `data/call-exports/` (not committed) and `data/calls-summary.md` (committed).

## Cloud

The agent runs on LiveKit Cloud (`python agent/main.py start`, region ap-south). The API and clinic run on Render. See [render.md](render.md). The web console runs on Vercel. Set the same environment variable names there. Do not put secret values in the repo.

## What is in each folder

| Folder | What it does |
| --- | --- |
| `agent/` | The voice agent, tools, FAQ, and call recorder |
| `api/` | `POST /calls`, `GET /calls`, `GET /calls/{id}`, end, result, cost, webhook |
| `clinic/` | Mock clinic slots. Booking the same slot twice fails |
| `web/` | Browser call, call history, and call detail |
| `scripts/` | Latency, cost, and export reports |
| `data/` | Saved reports. Raw transcripts stay out of git |

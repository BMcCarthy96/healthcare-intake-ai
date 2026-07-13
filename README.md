# Healthcare Intake AI

> **Synthetic data only — not for clinical use.**

Healthcare Intake AI is a document-to-action workflow engine for synthetic healthcare administrative intake packets. It extracts evidence-backed structured fields from digitally generated PDFs, applies deterministic completeness rules, routes uncertainty to a reviewer, and records an auditable workflow history.

It is intentionally an applied-software-engineering project: typed APIs, durable state, document evidence, validation, review controls, evaluations, retry-safe operations, and a polished operations UI. It does not diagnose, recommend treatment, determine urgency, or make coverage decisions.

## Quick start

```powershell
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The API is available at `http://localhost:8000/docs`.

For a guided demo script — including sample PDFs to upload (`uv run python
scripts/generate_sample_packets.py` writes them to `examples/`) — see
[docs/walkthrough.md](docs/walkthrough.md).

## Product flow

1. Create an intake case and upload a synthetic, text-based PDF.
2. Start processing with an idempotency key.
3. Extract a typed record plus page-level evidence using a deterministic local model stub.
4. Apply deterministic validation and routing.
5. Review uncertain cases, correct fields, request information, or approve a mock export.
6. Inspect audit history, processing metadata, and evaluation results.

## Local services

`docker-compose.yml` provides PostgreSQL, Redis, MinIO, API, worker, frontend, and mock export services for the full local stack. Docker mode enables Dramatiq processing through Redis. The default developer path uses SQLite, local file storage, and inline processing so the app can run without Docker.

## Deployment

The public demo runs the frontend on Vercel and the API on Render:

- **API (Render):** [render.yaml](render.yaml) is a one-click blueprint — Docker build of
  `backend/`, SQLite on the instance disk (the synthetic demo resets on redeploy by design),
  migrations applied at boot, health check on `/health/live`.
- **Frontend (Vercel):** deploy `frontend/` with `NEXT_PUBLIC_API_URL` pointing at the
  Render API URL.

## Safety boundary

- No real PHI or production healthcare integrations.
- No clinical decisions or unreviewed exports.
- PDF contents are treated as untrusted data, never as instructions.
- API keys are read only from environment variables and are never committed.

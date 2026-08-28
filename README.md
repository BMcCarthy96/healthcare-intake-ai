# IntakeFlow

[![CI](https://github.com/BMcCarthy96/healthcare-intake-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/BMcCarthy96/healthcare-intake-ai/actions/workflows/ci.yml)

> Evidence-first, human-governed healthcare administrative intake operations.
>
> **Synthetic data only · Not for clinical use.**

IntakeFlow is a recruiter-facing flagship project showing how to build a trustworthy AI workflow, not just call a model. It turns synthetic multi-document intake packets into typed, evidence-backed proposals; deterministic policy validates and routes them; a reviewer corrects or approves the record; and a retry-safe mock export records the complete decision trail.

The product story is deliberately honest:

> Models propose. Rules decide. People approve.

The default extractor is a deterministic rules baseline. An optional Anthropic adapter implements the same typed provider contract for a read-only comparison; it can never change workflow state or authorize an export.

## See the flagship story

1. Open `/demo` (or click **Start 90-second walkthrough** on `/`). A fresh anonymous workspace is isolated with a 60-minute TTL.
2. Follow **Contradictory packet + prompt injection**. It contains two conflicting synthetic member IDs and instruction-like document text.
3. Inspect rendered pages, document-local page numbers, native/OCR provenance, evidence quotes, normalized fields, and deterministic findings.
4. Correct the member ID with reviewer rationale. The correction creates extraction version 2, re-grounds the exact value to the insurance-card page, and leaves version 1 immutable.
5. Export from the guided exception. Its first attempt deliberately records a 429, returns the case to `ready_for_export`, and succeeds on retry with the same idempotency key.
6. Finish at `/proof` for persisted evaluation scores, quality gates, build metadata, architecture, and explicit limits.

The guided tour operates real controls and survives navigation, refresh, pause, restart, and workspace reset. The same scenario manifest drives seeding, tour copy, tests, and the recording script.

## What the demo proves

- **AI boundaries:** untrusted document text can propose fields but cannot issue workflow instructions.
- **Grounding:** each field carries document-local page identity, quote, character span, source mode, confidence, and normalized evidence boxes; exact reviewer corrections receive distinct reviewer-grounded provenance.
- **Workflow reliability:** explicit state transitions, durable processing jobs, database idempotency constraints, bounded worker retries, and export attempt history.
- **Human governance:** stale extraction reviews are rejected; reviewer corrections create immutable versions; export requires approval for the current version.
- **Recovery:** downstream 429/5xx/timeouts are classified as retryable; permanent 4xx failures are terminal; HMAC-signed payloads include correlation and idempotency headers.
- **Quality proof:** 80 development and 40 locked challenge packets cover clean, missing, contradictory, duplicate, corrupt, adversarial, and format-variation cases; CI also enforces at least 80% backend coverage.

## Run locally

### Lightweight developer mode

```powershell
cd backend
uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

In another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The typed API and OpenAPI explorer are at [http://localhost:8000/docs](http://localhost:8000/docs).

### Full local stack

```powershell
docker compose up --build -d
```

This runs PostgreSQL, Redis, MinIO, the API, Dramatiq worker, mock downstream export service, and Next.js. Health checks:

```powershell
Invoke-WebRequest http://localhost:8000/health/live
Invoke-WebRequest http://localhost:8000/health/ready
```

The public workspace keeps arbitrary uploads and evaluation writes disabled. Lightweight local mode can enable synthetic uploads with `ALLOW_PUBLIC_UPLOADS=true` and local evaluation runs with `ENABLE_PUBLIC_EVALS=true`.

## Quality checks and proof artifact

```powershell
cd backend
uv run ruff check app tests scripts
uv run alembic upgrade head
uv run pytest -q
uv run mypy app
uv run python scripts/generate_eval_cases.py
uv run python scripts/generate_proof_manifest.py

cd ../frontend
npm run lint
npm run build
npx playwright install --with-deps chromium
npm run test:e2e
```

CI runs deterministic evaluations on every pull request, publishes `recruiter-proof.json` as an artifact, and keeps live-provider checks out of the merge gate. The proof endpoint (`GET /v1/proof`) reads persisted evaluation state; it does not embed hand-authored scores.

## API surface

- `POST /v1/demo/sessions` — provision an isolated synthetic workspace and scenario manifest.
- `POST /v1/demo/sessions/{id}/reset` — reset the workspace to the exact seed.
- `GET /v1/demo/manifest` — return tour/scenario metadata.
- `GET /v1/cases?status=&risk=&query=&cursor=&limit=` — filtered queue with an `X-Next-Cursor` response header.
- `POST /v1/cases/{id}/process` — idempotent processing request with job metadata.
- `GET /v1/jobs/{id}` — stage, progress, attempts, and failure classification.
- `GET /v1/documents/{id}/pages/{page}` and `/image` — workspace-scoped page text, provenance, and rendered evidence asset.
- `POST /v1/cases/{id}/review` (or `/reviews`) — approve, request information, or create an immutable correction version.
- `POST /v1/cases/{id}/export` (or `/exports`) and `GET /v1/cases/{id}/exports` — signed, retry-safe export and immutable attempt history.
- `POST /v1/cases/{id}/model-comparisons` — bounded, read-only optional Anthropic comparison.
- `GET /v1/evals` — persisted deterministic evaluation history; `POST /v1/evals` is an explicit local/CI capability gated by `ENABLE_PUBLIC_EVALS`.
- `GET /v1/meta` and `GET /v1/proof` — non-secret version and quality provenance.

## Architecture

```text
Next.js reviewer console
        │  session token + correlation ID
FastAPI API ───── PostgreSQL / SQLite ───── immutable audit + versions
        │                              └── jobs, exports, model comparisons
        ├── PDF validation → native text / Tesseract OCR → rendered pages
        ├── typed extraction provider (rules baseline or optional Anthropic)
        ├── deterministic evidence + policy validation → explicit state machine
        └── reviewer decision → HMAC-signed mock downstream export
                      ▲
                Redis / Dramatiq worker
```

Important persistence decisions are documented in [docs/architecture.md](docs/architecture.md), [docs/model-routing.md](docs/model-routing.md), and [docs/threat-model.md](docs/threat-model.md). The step-by-step script is [docs/walkthrough.md](docs/walkthrough.md); operations and deployment notes are in [docs/runbook.md](docs/runbook.md).

## Deployment

- **Frontend:** deploy the `frontend/` directory to Vercel (set the project Root Directory to `frontend` and `NEXT_PUBLIC_API_URL` to the Render API URL).
- **API + worker:** [render.yaml](render.yaml) provisions the Docker API, a worker, private HMAC-validating mock downstream, managed PostgreSQL, and Key Value/Redis. Configure `CORS_ORIGINS` and S3-compatible credentials in Render; the blueprint generates and shares the downstream HMAC secret.
- **Object storage:** production should use an S3-compatible bucket with a lifecycle rule for abandoned demo assets. Local mode uses `backend/data/documents`.

After deployment, verify `/health/ready`, `GET /v1/meta`, `POST /v1/demo/sessions`, and the seven-step tour from a fresh incognito session. The frontend and API commit metadata should match the release being reviewed.

## Safety boundary and intentional limits

- All names, identifiers, documents, and metrics are synthetic.
- This is not a diagnostic, treatment, urgency, coverage, utilization-management, or clinical decision system.
- There is no HIPAA-compliance claim, real PHI, EHR/FHIR integration, or autonomous external action.
- The public demo uses anonymous TTL-scoped workspaces, not enterprise authentication/RBAC.
- The Anthropic adapter is optional, budgeted, clearly labeled, and read-only.
- Optional comparison calls are limited per workspace, bounded by a global daily budget, and protected by a persisted failure circuit breaker.
- Malware scanning, signed user URLs, formal retention policy, production key management, penetration testing, legal review, and a business-associate agreement are prerequisites for any real-data deployment.

## Repository map

| Area | Purpose |
| --- | --- |
| `backend/app/domain.py` | Explicit status machine and legal transitions |
| `backend/app/services.py` | Processing, validation, review, export, and idempotency rules |
| `backend/app/documents.py` | PDF validation, native extraction, OCR, page rendering, evidence boxes |
| `backend/app/demo.py` | Versioned scenarios, workspace provisioning, and tour manifest |
| `frontend/app/demo` | Isolated queue and real-control guided walkthrough |
| `frontend/app/cases` | Evidence viewer, correction controls, export inspector, audit timeline |
| `frontend/app/proof` | Recruiter-facing technical proof surface |
| `evals/datasets` | Checked-in synthetic development/challenge packets |
| `mock-services/downstream-export` | Deterministic retry/idempotency contract test service |

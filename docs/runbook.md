# Local and release runbook

## Lightweight developer mode

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

Open `http://localhost:3000`, then choose **Start 90-second walkthrough**. This path uses SQLite, local page assets, the deterministic rules baseline, and inline processing.

## Full stack

```powershell
docker compose up --build -d
```

Services: PostgreSQL, Redis, MinIO, API, Dramatiq worker, mock downstream export, and Next.js. Confirm:

```powershell
Invoke-WebRequest http://localhost:8000/health/live
Invoke-WebRequest http://localhost:8000/health/ready
```

Use `docker compose logs -f api worker` when diagnosing processing. The worker owns extraction; the API owns request validation and durable state changes.

## Environment switches

| Variable | Local default | Purpose |
| --- | --- | --- |
| `MODEL_PROVIDER` | `stub` | Deterministic rules baseline; `anthropic` is optional |
| `ALLOW_PUBLIC_UPLOADS` | `false` | Keep arbitrary uploads out of the public demo |
| `OCR_ENABLED` | `true` | Tesseract fallback for image-only pages |
| `ASYNC_PROCESSING` | `false` | Inline local mode; `true` uses Redis/Dramatiq |
| `MOCK_EXPORT_MODE` | `success` | Contract modes include `first_attempt_rate_limit`, `timeout`, and `permanent_failure` |
| `MOCK_EXPORT_HOSTPORT` | unset | Render-provided private mock host/port; converted to the `/exports` URL |
| `DOWNSTREAM_HMAC_SECRET` | local-only value | Secret used for `X-Signature`; rotate in deployment |
| `ENABLE_LIVE_MODEL_COMPARE` | `false` | Bounded read-only provider comparison |
| `ENABLE_PUBLIC_EVALS` | `false` | Allows `POST /v1/evals`; keep disabled on public deployments |
| `AUTO_SEED_PROOF` | `false` | Seeds one deterministic held-out proof run when an empty deployment starts |

## Quality gates

Run in this order:

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

The deterministic suite has 80 development and 40 challenge packets. Its gates are zero false-ready cases, at least 95% routing and field macro-F1, 100% valid evidence references, and at least 80% backend test coverage. Live-provider results are reported separately and are not merge gates.

## Release smoke test

1. Apply migrations to a fresh database.
2. Check `/health/ready` and `/v1/meta`.
3. `POST /v1/demo/sessions`; save the returned token, then `GET /v1/demo/manifest` with `X-Demo-Session`.
4. Verify exactly five cases, including the exception-recovery, scanned, and retryable-export scenarios.
5. Open the recommended case from the demo UI; verify page image/evidence endpoints.
6. Correct and approve the exception; verify a new extraction version and stale-review rejection.
7. Export the retryable scenario twice with the same key; verify attempt 1 is 429/retryable and attempt 2 succeeds.
8. Open `/proof` and verify the auto-seeded held-out metrics and commit metadata. In local/CI mode with `ENABLE_PUBLIC_EVALS=true`, also run an evaluation and confirm the newer persisted run.

## Deployment notes

- Vercel project Root Directory must be `frontend`.
- Render API and worker should use managed PostgreSQL and Key Value/Redis; do not deploy production SQLite.
- Configure exact `CORS_ORIGINS` and S3 credentials as secrets. The blueprint shares a generated `DOWNSTREAM_HMAC_SECRET` with the private mock service.
- Set an object-store lifecycle rule for abandoned demo documents/page images.
- Keep `ALLOW_PUBLIC_UPLOADS=false` on the public deployment.
- Keep `ENABLE_PUBLIC_EVALS=false`; use `AUTO_SEED_PROOF=true` so a fresh public proof page is populated without exposing a write endpoint.

## Troubleshooting

- **Failed to fetch:** start API, verify CORS, then click **Try again**.
- **Expired demo:** start a new workspace; tokens are intentionally short-lived.
- **OCR unavailable:** install the Tesseract binary and keep `OCR_ENABLED=true`; image-only PDFs otherwise fail safely.
- **Export 429:** retry with the exact same idempotency key; do not generate a new key for a replay.
- **Stale review:** reload the case and submit against its displayed extraction version.
- **Unexpected model score:** inspect the checked-in packet in `evals/datasets`, then reproduce with `generate_proof_manifest.py`.

## Release boundary

The public deployment is a synthetic demonstration environment. Keep uploads disabled unless object storage, malware scanning, retention, rate limiting, and an explicit privacy review have been completed.

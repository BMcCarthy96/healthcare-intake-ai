# Local runbook

## Developer mode

1. Run `uv sync --extra dev` in `backend/`.
2. Run `uv run alembic upgrade head` in `backend/` to create the local SQLite schema.
3. (Optional) Regenerate eval datasets: `uv run python scripts/generate_eval_cases.py`. Each
   dataset case embeds the synthetic document text it is scored against, and `POST /v1/evals`
   runs those documents through the configured model gateway (the deterministic stub by
   default; the Anthropic provider when `MODEL_PROVIDER=anthropic`).
4. Start the API: `uv run uvicorn app.main:app --reload --port 8000`.
5. Run `npm install` then `npm run dev` in `frontend/`.
6. Open `http://localhost:3000` and choose **Load a complete synthetic demo**.

For a guided demo script, see [walkthrough.md](walkthrough.md).

## Full local stack

Run `docker compose up --build -d` from the repository root. This starts PostgreSQL, Redis, MinIO, the API, Dramatiq worker, mock export service, and the Next.js UI. Confirm health with `Invoke-WebRequest http://localhost:8000/health/ready`, then open `http://localhost:3000`.

## Quality checks

```powershell
cd backend
uv run ruff check app tests
uv run alembic upgrade head
uv run pytest -q
uv run mypy app

cd ../frontend
npm run lint
npm run build
```

## Expected workflow

- A complete packet becomes `ready_for_export`.
- A reviewer records approval or corrections.
- Only then does **Approve mock export** become available.
- An idempotent replay returns the original processing/export outcome.
- Missing required fields become `missing_information`.
- Contradictions, unsupported evidence, or instruction-like text become `review_required`.

## Troubleshooting

- If the browser shows `Failed to fetch`, start the API and ensure `CORS_ORIGINS` contains both `http://localhost:3000` and `http://127.0.0.1:3000`.
- If PDF upload fails, use a digitally generated PDF with selectable text; OCR is deferred by design.
- If using `MODEL_PROVIDER=anthropic`, install `uv sync --extra anthropic`, provide `ANTHROPIC_API_KEY`, and run the evaluation suite before treating that route as trusted.

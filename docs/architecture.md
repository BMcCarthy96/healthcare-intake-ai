# Architecture decision record

IntakeFlow separates untrusted extraction from deterministic workflow control. That boundary is the central design decision: the model can suggest a value, but it cannot transition a case, approve a record, or call an external system.

## Runtime topology

```text
Browser
  │ HTTPS, X-Demo-Session, X-Correlation-ID
  ▼
Next.js reviewer console ────────────────┐
  │                                      │
  └────────────── FastAPI API ───────────┼── PostgreSQL (production)
                     │                   ├── Redis / Dramatiq worker
                     │                   ├── S3-compatible object store
                     │                   └── mock downstream export
                     ▼
        PDF validation → page rendering → native text / Tesseract OCR
                     ▼
        typed extraction provider → evidence verification → policy routing
                     ▼
        reviewer correction/approval → signed export attempt + audit event
```

The local developer path swaps in SQLite, filesystem storage, and inline processing. Docker Compose exercises the production-shaped PostgreSQL, Redis, MinIO, worker, and downstream contract.

## Data flow

1. `Document` stores a content hash, generated storage key, page count, extracted page text, page provenance, and rendered page image keys. Filenames never become storage paths.
2. `ModelGateway` returns an `IntakeRecord` proposal. The default provider is the deterministic rules baseline; Anthropic is an optional adapter with the same interface.
3. `services.validate_record` checks required fields, formats, evidence quotes, OCR quality, prompt-injection text, and contradictions. The model does not choose the route.
4. `ExtractionResult` is immutable by version. `IntakeCase.latest_extraction_id` points to the current version; reviewer corrections create a replacement row, synchronize the field projection, and retain the original. Corrected values are deterministically re-grounded only when an exact source-page match exists; otherwise the new value carries no fabricated evidence.
5. `ReviewDecision` references the extraction version reviewed. Export refuses approvals attached to an older version.
6. `ExportAttempt` captures the canonical payload, HMAC signature, idempotency key, downstream response, attempt number, and retry classification.
7. `AuditEvent` records every state transition and consequential action with a correlation ID.

## State machine

```text
received → queued → processing → missing_information
                         │      ↘ review_required
                         │       ↘ ready_for_export → exporting → completed
                         └───────────────────────────────┘       │
                                  retryable export failure ───────┘
```

`failed` is a terminal processing/export state that can be reprocessed when the action is safe. A downstream 429/5xx/timeout returns the case to `ready_for_export` and preserves the failed attempt. A permanent 4xx transitions to `failed` and requires a new reviewer action.

## Workspace isolation

`POST /v1/demo/sessions` creates a random opaque token, stores only its SHA-256 hash, and seeds five cases whose foreign key points to that workspace. Every demo request is filtered by the token and expiry. Reset deletes and reseeds the workspace, refreshes its TTL, and clears client tour state. Expired rows are purged when a new workspace is provisioned; object-store lifecycle rules remove abandoned blobs.

This is intentionally anonymous demo isolation, not enterprise identity. Authentication, tenant administration, RBAC, and production retention policy are deferred until real-data scope exists.

## Reliability controls

- Database uniqueness on `(case_id, idempotency_key)` for processing and export attempts.
- Transactional status change + event + job/attempt creation.
- Row-locking query paths on supported relational databases; SQLite remains a local single-process mode.
- Dramatiq retries are bounded (three attempts, capped backoff).
- Downstream requests carry `Idempotency-Key`, `X-Correlation-ID`, and an HMAC `X-Signature` over canonical JSON.
- Mock downstream replay returns the same accepted record for a reused key.
- Job endpoint exposes stage, progress, retry attempt, and failure classification.

## Why the UI is split into `/`, `/demo`, `/cases/:id`, and `/proof`

- `/` explains the thesis and offers the shortest entry point.
- `/demo` is a disposable, seeded operations queue with a guided tour.
- `/cases/:id` is the evidence workspace used for free exploration and review.
- `/proof` surfaces measured evaluations, quality gates, provenance, architecture, and limitations.

Keeping these surfaces separate makes the recruiter narrative legible while preserving a real workflow underneath.

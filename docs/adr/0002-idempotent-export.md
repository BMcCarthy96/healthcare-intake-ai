# ADR 0002: Treat exports as an idempotent outbox operation

## Decision

An export operation is keyed by `(case_id, idempotency_key)`. Each attempt is an immutable record, the payload is signed, and retryable 429/5xx/timeout outcomes return the case to `ready_for_export` without losing the failed attempt.

## Consequences

Retries are safe to demonstrate and audit, while the mock downstream can enforce exactly-once behavior. A production adapter still needs a durable queue worker and operational retry/alert limits.

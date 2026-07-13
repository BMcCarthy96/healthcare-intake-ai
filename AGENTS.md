# Healthcare Intake AI operating guide

This is a synthetic-data-only administrative workflow demo. It is not for clinical use and must never make diagnosis, treatment, urgency, coverage, or autonomous external-action decisions.

## Read first

- `README.md` for product boundaries and run commands.
- `docs/architecture.md` for system decisions.
- `docs/CONTEXT_INDEX.md` to limit context loading.
- `backend/app/schemas.py` before changing API contracts.

## Non-negotiable rules

- Never add real PHI, secrets, private AIOps files, absolute local paths, or unrelated project context.
- Models may extract structured data only; deterministic workflow code owns status changes.
- Every state transition must create an audit event.
- Processing and export must remain idempotent.
- Keep edits small and add focused tests with each behavior change.

## Verification order

1. Type or syntax check
2. Lint
3. Focused backend/frontend tests
4. End-to-end tests when a user flow changes

## Completion report

State files changed, tests run with results, deliberate deviations, known limitations, and the next safe task.

# Threat model

## Scope

This project is a synthetic, administrative workflow demonstration. It intentionally does not process real PHI, connect to EHRs, or make clinical decisions.

## Assets

- Synthetic intake PDFs and extracted page text.
- Structured extraction proposals and reviewer corrections.
- Audit history, workflow state, and evaluation records.
- Model-provider credentials when an optional live adapter is enabled.

## Controls

| Threat | Control |
|---|---|
| Real or sensitive data enters a public demo | UI/README synthetic-only boundary, repository hygiene checks, no production integrations |
| Non-PDF or oversized upload | PDF signature, extension, and size validation |
| Path traversal through filename | Server-generated storage keys and sanitized filenames |
| Prompt injection in document text | Document text is untrusted data; instruction-like content routes to human review |
| Model output changes workflow state | Only deterministic domain services transition state |
| Unsupported extraction accepted | Required fields require evidence; evidence must match extracted page text |
| Duplicate process/export action | Idempotency keys and persisted event/job history |
| Automatic external export | Explicit reviewer approval is required before mock export |
| Secret exposure | Environment-only configuration; `.env` ignored; no credentials in fixtures |

## Deferred before any real-data use

Authentication, tenant isolation, encryption/key management, formal retention/deletion policies, signed document URLs, malware scanning, penetration testing, legal review, HIPAA controls, and a business-associate agreement are all required before using anything other than synthetic data.

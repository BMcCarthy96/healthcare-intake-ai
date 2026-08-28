# Threat model

## Scope and trust boundaries

IntakeFlow is a synthetic, administrative workflow demonstration. The browser, uploaded/document text, model provider, and mock downstream are treated as untrusted or semi-trusted inputs. Deterministic backend policy and persisted audit state are the control plane.

    untrusted PDF/text -> parser/OCR -> model proposal (untrusted)
                                      |
                                      v
                         deterministic validation + state machine
                                      |
                              reviewer decision
                                      |
                         signed, idempotent mock export

The system deliberately does not process real PHI, connect to EHRs, or make clinical decisions.

## Assets

- Synthetic PDFs, rendered page images, and extracted page text.
- Proposed and corrected administrative records.
- Extraction versions, validation issues, review decisions, processing jobs, and export attempts.
- Audit history and correlation IDs.
- Optional provider credentials and downstream HMAC secret.

## Threats and controls

| Threat | Control in this project |
| --- | --- |
| Sensitive data enters a public demo | Synthetic-only UI/README boundary; public arbitrary uploads disabled; no production integrations |
| Cross-session case access | Random opaque session token; only SHA-256 token hash persisted; workspace foreign-key filtering on case/document/page/job/export/model routes; expiry checks |
| Abandoned demo data persists forever | Expired workspaces purged during provisioning; object-store lifecycle rule documented for blobs |
| Non-PDF, oversized, or malformed upload | Extension/signature/size validation; PyMuPDF parse failure becomes a safe 422 |
| Path traversal through filename | Server-generated key using sanitized basename and content hash |
| Scanned page loses grounding | Tesseract OCR captures token coordinates/confidence; page images are rendered at ingestion; low-confidence critical evidence routes to review |
| Prompt injection in document text | Text is data, never instructions; instruction-like content creates untrusted_instruction_detected |
| Model output changes workflow state | Only deterministic services call the explicit transition function |
| Unsupported or stale evidence is accepted | Quotes are verified against stored page text; every review/export references a specific extraction version |
| Duplicate processing/export | Database uniqueness constraints and persisted idempotency keys; retries reuse the same export key |
| Downstream replay creates duplicate record | Canonical payload HMAC plus Idempotency-Key; mock downstream returns idempotent replay |
| Permanent downstream failure is retried forever | 429/5xx/timeouts are retryable; other 4xx responses are terminal and visible |
| Secret exposure | Environment-only configuration; .env ignored; raw provider output is not exposed in the public UI |
| Browser framing/content sniffing | API emits X-Frame-Options and X-Content-Type-Options; CORS uses exact configured origins |

## Explicit non-goals

This is not authentication, enterprise tenant isolation, RBAC, encryption/key management, malware scanning, formal retention/deletion policy, signed user URLs, HIPAA compliance, or an EHR/FHIR connector. Those are required before any real-data use and are intentionally outside the flagship scope.

## Review checklist before real-data scope

1. Threat-model and privacy review by the owning organization.
2. Authentication, tenant authorization, and audit access controls.
3. Encrypted storage/transport with managed key rotation.
4. Malware/DLP scanning and content-type enforcement.
5. Formal retention, deletion, backup, and incident-response policies.
6. Provider contract, data-processing terms, legal review, and business-associate agreement.
7. Penetration testing, dependency/container scanning, and load testing.

The repository intentionally documents these as production follow-ups rather than implying that a synthetic showcase is a clinical or HIPAA-ready system.

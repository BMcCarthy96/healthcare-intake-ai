# Model routing and provider disclosure

## Default route: deterministic rules baseline

The public demo uses StubModelGateway, a deterministic parser with no network call or API key. It is intentionally labeled a **rules baseline**, not marketed as an LLM. Given the same page text it produces the same typed IntakeRecord, evidence quote, and timing.

The route is:

1. Validate the PDF signature, size, and parseability.
2. Extract native text and positioned words with PyMuPDF.
3. Render every page; for image-only pages, run Tesseract OCR and retain token coordinates/confidence.
4. Ask the provider for typed candidate fields only.
5. Verify evidence quotes against stored page text and attach document/page/character/box provenance.
6. Apply deterministic required-field, format, contradiction, prompt-injection, duplicate, and OCR-quality policy.
7. Route to missing information, human review, ready for export, or failure.
8. Require a reviewer decision before export.

No provider output can transition a case or invoke downstream export.

## Optional Anthropic comparison

Set MODEL_PROVIDER=anthropic with ANTHROPIC_API_KEY (and install the anthropic extra) for a full extraction provider. The adapter uses the same IntakeRecord schema and tool-call contract. The UI’s Compare optional model run action is read-only:

- It is available only inside an isolated demo workspace.
- The public deployment keeps it disabled by default.
- A per-workspace budget, global daily budget, circuit breaker, and cache key (document hashes, prompt/schema versions, and provider model) prevent accidental repeated spend.
- Provider errors, malformed tool output, timeouts, and unavailable credentials remain visible; they never silently replace the baseline.
- Comparison records do not update the case, extraction version, status, approval, or export payload.

## Quality policy

A provider change is trusted only after deterministic development and held-out evaluation. The checked-in suite contains 80 development and 40 challenge packets across clean, missing, contradictory, duplicate, corrupt, adversarial, and formatting-variation categories.

The proof artifact reports:

- Routing accuracy and macro-F1.
- Field accuracy and macro-F1 over required administrative fields.
- False-ready count (must be zero for the safety gate).
- Evidence validity.
- Category-level results, so a green aggregate cannot hide a failure class.

Live-provider scores are informative and budgeted, not merge gates. A lower-cost route should not ship if it regresses the primary held-out metric or increases false-ready behavior.

## Redaction and logging

Raw provider output is stored only as structured JSON for local auditability and is not rendered as an arbitrary HTML surface. Production deployments should add field-level redaction, secret-managed logs, retention controls, and provider data-processing review before real-data scope.

## Release boundary

The checked-in demo runs with the deterministic stub provider. Live-provider comparison is an explicitly disabled, budgeted opt-in and must be validated against the held-out packet before it is enabled for a deployment.

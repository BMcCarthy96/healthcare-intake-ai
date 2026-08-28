# ADR 0004: Preserve page provenance across native text and OCR

## Decision

Ingestion stores page text, rendered images, normalized word coordinates, source mode, and OCR confidence. Critical extracted fields carry document/document-local-page/quote/character-span/box references and are rejected or routed to review when evidence cannot be verified. Reviewer corrections use distinct provenance and receive evidence only when the corrected value can be exactly re-grounded to a stored source page.

## Consequences

The case workspace can show a recruiter the source behind a proposal and expose scanned-document uncertainty. OCR quality depends on the bundled Tesseract runtime; real-data deployments require additional malware, retention, and privacy controls.

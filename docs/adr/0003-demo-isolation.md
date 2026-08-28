# ADR 0003: Give every public walkthrough an expiring workspace

## Decision

`POST /v1/demo/sessions` provisions an opaque token-backed workspace with a 60-minute TTL and five deterministic synthetic cases. Case, document, job, comparison, and audit reads are scoped to that workspace; reset recreates the same manifest.

## Consequences

Recruiters can open multiple sessions without seeing one another's state, and abandoned demo data has a bounded lifetime. The public surface remains intentionally anonymous and is not a substitute for production authentication or RBAC.

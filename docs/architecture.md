# Architecture

Healthcare Intake AI separates untrusted document extraction from deterministic workflow control.

```text
Next.js reviewer UI
        |
FastAPI API ── PostgreSQL/SQLite ── Audit events
        |              |
        |              └── intake cases, documents, model runs, review decisions
        |
Background processing
        |
PDF text extraction → structured model gateway → evidence validation → deterministic routing
        |
Reviewer approval → mock downstream export
```

The default model provider is a deterministic stub. A provider adapter may produce proposed fields and evidence, but only domain services may transition case state. Every transition is recorded as an audit event.

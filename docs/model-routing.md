# Model routing

The default route is a deterministic local stub so public demos and tests remain reproducible.

1. Validate and hash documents before any model call.
2. Use cached output when document hash, prompt version, schema version, and model match.
3. Use the cheap tier for first-pass structured extraction.
4. Retry malformed structured output once at the same tier.
5. Use a balanced fallback only for unrecoverable schema failure.
6. Route low-evidence or contradictory output to a human reviewer; do not spend automatically to override uncertainty.
7. Use premium models only for offline benchmark comparison and failure analysis.

Never promote a lower-cost route without held-out evaluation evidence. A route must meet all quality gates and remain within two percentage points of the balanced route on the primary metric.

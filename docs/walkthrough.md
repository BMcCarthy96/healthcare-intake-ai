# 90-second guided walkthrough

Use synthetic data only. The walkthrough is designed to show a recruiter the system’s judgment points, not to imply clinical automation.

## The spoken setup (10 seconds)

> “IntakeFlow turns administrative document packets into evidence-backed workflow proposals. The extractor is untrusted, deterministic rules route the work, and a reviewer must approve anything that can be exported.”

## The seven beats

1. **Queue (0–10s):** Click **Start 90-second walkthrough**. Call out the isolated workspace, five statuses, and 60-minute expiry.
2. **Exception packet (10–20s):** Click the highlighted **Contradictory packet + prompt injection** card (or use the coach’s **Next →** button). It contains a referral and synthetic insurance card with conflicting member IDs plus instruction-like text; either path preserves the guided tour.
3. **Grounding (20–32s):** In the evidence viewer, switch document tabs and point to the rendered page. Each proposal exposes its document-local page, quote, extraction confidence, source mode, and normalized boxes.
4. **Decision trace (32–45s):** Show `contradictory_document_values` and `untrusted_instruction_detected`. Explain that the model never selected `review_required`; deterministic policy did.
5. **Versioned review (45–58s):** Click the coach action **Apply correction + approve**. Point out “extraction v2,” the reviewer rationale, the new **Reviewer-grounded exact match** label on the insurance-card value, and the immutable prior proposal.
6. **Recovery (58–75s):** Click **Trigger controlled 429**, inspect attempt 1, then click **Retry same export operation**. The case remains ready after the first attempt, both attempts stay visible, and the identical idempotency key succeeds without duplicating the downstream record.
7. **Proof (75–90s):** Finish at `/proof`. Show measured routing/field metrics, false-ready count, evidence validity, quality gates, commit metadata, architecture, and limitations.

The coachmarks use stable `data-tour-target` anchors and real buttons/links. `Escape` pauses the overlay; arrow keys move between steps; **Restart from the beginning** returns to `/demo`; reset re-seeds all five cases.

## Five self-guided scenarios

| Scenario | Expected route | What to point out |
| --- | --- | --- |
| Clean packet | `ready_for_export` | Evidence-backed happy path |
| Missing member identifier | `missing_information` | Required-field gate |
| Contradictory + adversarial | `review_required` | Cross-document conflict and prompt-injection handling |
| Scanned packet | `ready_for_export` or review if OCR quality is low | Tesseract provenance and rendered page |
| Retryable export | `ready_for_export` → `completed` | 429 recovery and exactly-once idempotency |

## Five-minute technical extension

- With `ENABLE_PUBLIC_EVALS=true` in a local environment, run **Development evaluation** (80 deterministic packets) and **Challenge evaluation** (40 held-out packets); compare routing accuracy, macro-F1, false-ready count, evidence validity, and category metrics. Public deployments expose persisted proof but do not permit evaluation writes.
- Open the scanned packet and show `source_mode=ocr`, source confidence, and page image endpoint.
- Click **Compare optional model run** only when `ENABLE_LIVE_MODEL_COMPARE=true`; otherwise explain that the public deployment deliberately does not spend API budget. Comparison output is read-only and cached by document/schema/model key.
- Open `/docs` and show the job, review, export, proof, and page contracts.
- Explain the deployment shape: Vercel frontend, always-on Render API/worker, managed PostgreSQL/Redis, S3-compatible storage, and a mock downstream contract service.

## If the API is cold or unavailable

The UI should show a recoverable error with **Try again**, not an endless spinner. Start the backend, confirm `/health/ready`, then reload. Public sessions can be restarted from `/demo`; no real data or manual database setup is required.

## Local packet generation

```powershell
cd backend
uv run python scripts/generate_sample_packets.py
```

The generated PDFs are synthetic fixtures. Arbitrary uploads are allowed only in a local environment explicitly configured for synthetic uploads; the public workspace uses bundled packets.

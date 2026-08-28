# Context index

Load only the documents and source files needed for the task.

| Task | Read first |
|---|---|
| API contract | `backend/app/schemas.py`, `backend/app/main.py` |
| Workflow or routing | `backend/app/domain.py`, `backend/app/services.py` |
| Persistence | `backend/app/models.py`, `backend/app/db.py` |
| Document processing | `backend/app/documents.py`, `backend/app/model_gateway.py` |
| Evaluations | `backend/app/evaluations.py`, `evals/datasets/` |
| UI | `frontend/app/`, `frontend/components/` |
| Deployment | `docker-compose.yml`, `.github/workflows/` |
| Recruiter proof | `frontend/app/proof/`, `backend/scripts/generate_proof_manifest.py`, `GET /v1/proof` |
| Guided demo | `backend/app/demo.py`, `frontend/app/demo/`, `frontend/components/tour-coach.tsx`, `docs/walkthrough.md` |
| Architecture decisions | `docs/adr/0001-model-boundary.md`, `docs/adr/0002-idempotent-export.md`, `docs/adr/0003-demo-isolation.md`, `docs/adr/0004-ocr-evidence.md` |

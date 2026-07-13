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

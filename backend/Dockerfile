FROM python:3.12-slim
WORKDIR /app
# Build context is the repo root (see render.yaml) so evals/ is reachable as a
# sibling of /app, mirroring the local layout that app/evaluations.py expects.
COPY backend/ ./
COPY evals/ /evals/
RUN pip install --no-cache-dir uv && uv sync --no-dev
# Binds to $PORT when the platform (e.g. Render) provides one; docker-compose overrides CMD.
CMD ["sh", "-c", "mkdir -p /app/data && uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

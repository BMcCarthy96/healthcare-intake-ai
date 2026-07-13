FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir uv && uv sync --no-dev
# Binds to $PORT when the platform (e.g. Render) provides one; docker-compose overrides CMD.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

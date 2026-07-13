from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    document_storage_path: Path
    model_provider: str
    cors_origins: list[str]
    max_upload_bytes: int
    async_processing: bool
    redis_url: str | None
    document_storage_backend: str
    s3_endpoint_url: str | None
    s3_bucket: str
    s3_access_key: str | None
    s3_secret_key: str | None
    mock_export_url: str | None
    mock_export_mode: str


def get_settings() -> Settings:
    storage_path = Path(os.getenv("DOCUMENT_STORAGE_PATH", "./data/documents"))
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/healthcare_intake.db"),
        document_storage_path=storage_path,
        model_provider=os.getenv("MODEL_PROVIDER", "stub"),
        cors_origins=[
            origin.strip()
            for origin in os.getenv(
                "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
            ).split(",")
        ],
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", "5242880")),
        async_processing=os.getenv("ASYNC_PROCESSING", "false").lower() == "true",
        redis_url=os.getenv("REDIS_URL") or None,
        document_storage_backend=os.getenv("DOCUMENT_STORAGE_BACKEND", "local").lower(),
        s3_endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
        s3_bucket=os.getenv("S3_BUCKET", "intake-documents"),
        s3_access_key=os.getenv("S3_ACCESS_KEY") or None,
        s3_secret_key=os.getenv("S3_SECRET_KEY") or None,
        mock_export_url=os.getenv("MOCK_EXPORT_URL") or None,
        mock_export_mode=os.getenv("MOCK_EXPORT_MODE", "success"),
    )

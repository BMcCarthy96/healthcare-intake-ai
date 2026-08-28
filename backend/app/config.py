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
    demo_session_ttl_minutes: int
    public_uploads_enabled: bool
    ocr_enabled: bool
    live_model_compare_enabled: bool
    evaluation_runs_enabled: bool
    proof_auto_seed_enabled: bool
    max_model_comparisons_per_session: int
    model_compare_daily_budget: int
    model_compare_circuit_failure_threshold: int
    model_compare_circuit_window_minutes: int
    downstream_hmac_secret: str
    app_version: str


def get_settings() -> Settings:
    storage_path = Path(os.getenv("DOCUMENT_STORAGE_PATH", "./data/documents"))
    mock_export_target = os.getenv("MOCK_EXPORT_URL") or os.getenv("MOCK_EXPORT_HOSTPORT")
    if mock_export_target and "://" not in mock_export_target:
        mock_export_target = f"http://{mock_export_target}"
    if mock_export_target and not mock_export_target.rstrip("/").endswith("/exports"):
        mock_export_target = f"{mock_export_target.rstrip('/')}/exports"
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
        mock_export_url=mock_export_target or None,
        mock_export_mode=os.getenv("MOCK_EXPORT_MODE", "success"),
        demo_session_ttl_minutes=int(os.getenv("DEMO_SESSION_TTL_MINUTES", "60")),
        public_uploads_enabled=os.getenv(
            "ALLOW_PUBLIC_UPLOADS", os.getenv("ALLOW_USER_UPLOADS", "false")
        ).lower()
        == "true",
        ocr_enabled=os.getenv("OCR_ENABLED", "true").lower() == "true",
        live_model_compare_enabled=os.getenv("ENABLE_LIVE_MODEL_COMPARE", "false").lower() == "true",
        evaluation_runs_enabled=os.getenv("ENABLE_PUBLIC_EVALS", "false").lower() == "true",
        proof_auto_seed_enabled=os.getenv("AUTO_SEED_PROOF", "false").lower() == "true",
        max_model_comparisons_per_session=int(os.getenv("MAX_MODEL_COMPARISONS_PER_SESSION", "1")),
        model_compare_daily_budget=int(os.getenv("MODEL_COMPARE_DAILY_BUDGET", "10")),
        model_compare_circuit_failure_threshold=int(
            os.getenv("MODEL_COMPARE_CIRCUIT_FAILURE_THRESHOLD", "3")
        ),
        model_compare_circuit_window_minutes=int(
            os.getenv("MODEL_COMPARE_CIRCUIT_WINDOW_MINUTES", "10")
        ),
        downstream_hmac_secret=os.getenv("DOWNSTREAM_HMAC_SECRET", "local-development-only"),
        app_version=os.getenv("APP_VERSION", "0.2.0"),
    )

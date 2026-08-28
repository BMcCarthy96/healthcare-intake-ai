from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class IntakeCase(Base):
    __tablename__ = "intake_cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    external_reference: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="received", index=True)
    source: Mapped[str] = mapped_column(String(100), default="web")
    workspace_id: Mapped[str | None] = mapped_column(
        ForeignKey("demo_workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    scenario: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    latest_extraction_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    documents: Mapped[list[Document]] = relationship(back_populates="case", cascade="all, delete-orphan")
    events: Mapped[list[AuditEvent]] = relationship(back_populates="case", cascade="all, delete-orphan")
    workspace: Mapped[DemoWorkspace | None] = relationship(back_populates="cases")


class DemoWorkspace(Base):
    __tablename__ = "demo_workspaces"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    scenario_version: Mapped[str] = mapped_column(String(30), default="v2")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cases: Mapped[list[IntakeCase]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("case_id", "sha256", name="uq_case_document_hash"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extracted_pages: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    case: Mapped[IntakeCase] = relationship(back_populates="documents")


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (UniqueConstraint("case_id", "idempotency_key", name="uq_processing_job_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(50), default="extract_intake")
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(40), default="queued")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    failure_classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    route_tier: Mapped[str] = mapped_column(String(20))
    prompt_version: Mapped[str] = mapped_column(String(30))
    schema_version: Mapped[str] = mapped_column(String(30))
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExtractionResult(Base):
    __tablename__ = "extraction_results"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_extraction_case_version"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True)
    model_run_id: Mapped[str] = mapped_column(ForeignKey("model_runs.id", ondelete="CASCADE"))
    normalized_record: Mapped[dict] = mapped_column(JSON)
    validation_status: Mapped[str] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True)
    extraction_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_results.id", ondelete="CASCADE"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(20))
    field_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True)
    extraction_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_results.id", ondelete="CASCADE"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(40))
    reviewer: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrections: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    correlation_id: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    case: Mapped[IntakeCase] = relationship(back_populates="events")


class ExportAttempt(Base):
    __tablename__ = "export_attempts"
    __table_args__ = (UniqueConstraint("case_id", "idempotency_key", name="uq_export_attempt_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    case_id: Mapped[str] = mapped_column(ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True)
    extraction_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_results.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200))
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="started", index=True)
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    downstream_record_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[list[ExportAttemptRecord]] = relationship(
        back_populates="operation", cascade="all, delete-orphan"
    )


class ExportAttemptRecord(Base):
    """Immutable attempt history for one idempotent export operation."""

    __tablename__ = "export_attempt_records"
    __table_args__ = (
        UniqueConstraint(
            "case_id", "idempotency_key", "attempt_number", name="uq_export_attempt_record"
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("export_attempts.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[str] = mapped_column(ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True)
    extraction_id: Mapped[str | None] = mapped_column(
        ForeignKey("extraction_results.id", ondelete="SET NULL"), nullable=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), index=True)
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    request_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    downstream_record_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operation: Mapped[ExportAttempt] = relationship(back_populates="attempts")


class ModelComparison(Base):
    __tablename__ = "model_comparisons"
    __table_args__ = (UniqueConstraint("workspace_id", "cache_key", name="uq_model_comparison_cache"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("demo_workspaces.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("intake_cases.id", ondelete="CASCADE"), index=True)
    cache_key: Mapped[str] = mapped_column(String(128), index=True)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    dataset: Mapped[str] = mapped_column(String(50), index=True)
    total_cases: Mapped[int] = mapped_column(Integer)
    matched_cases: Mapped[int] = mapped_column(Integer)
    routing_accuracy: Mapped[float] = mapped_column()
    field_accuracy: Mapped[float] = mapped_column(default=0.0)
    routing_macro_f1: Mapped[float] = mapped_column(default=0.0)
    field_macro_f1: Mapped[float] = mapped_column(default=0.0)
    false_ready_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_validity: Mapped[float] = mapped_column(default=1.0)
    category_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    results: Mapped[list[EvalCaseResult]] = relationship(
        back_populates="eval_run", cascade="all, delete-orphan"
    )


class EvalCaseResult(Base):
    __tablename__ = "eval_case_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    eval_run_id: Mapped[str] = mapped_column(ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(50), default="unknown")
    expected_status: Mapped[str] = mapped_column(String(50))
    actual_status: Mapped[str] = mapped_column(String(50))
    matched: Mapped[bool] = mapped_column()
    issue: Mapped[str | None] = mapped_column(Text, nullable=True)
    fields_matched: Mapped[int] = mapped_column(Integer, default=0)
    fields_compared: Mapped[int] = mapped_column(Integer, default=0)
    evidence_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    eval_run: Mapped[EvalRun] = relationship(back_populates="results")

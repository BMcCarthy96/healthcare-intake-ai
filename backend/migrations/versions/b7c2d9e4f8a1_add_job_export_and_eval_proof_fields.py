"""add job progress, export signatures, and evaluation proof metrics

Revision ID: b7c2d9e4f8a1
Revises: a2e7d9c4b6f1
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c2d9e4f8a1"
down_revision: str | Sequence[str] | None = "a2e7d9c4b6f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("processing_jobs", sa.Column("stage", sa.String(length=40), nullable=False, server_default="queued"))
    op.add_column("processing_jobs", sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("processing_jobs", sa.Column("failure_classification", sa.String(length=40), nullable=True))
    op.add_column("export_attempts", sa.Column("request_signature", sa.String(length=128), nullable=True))
    op.add_column("export_attempts", sa.Column("downstream_record_id", sa.String(length=100), nullable=True))
    op.add_column("export_attempts", sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "export_attempt_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("operation_id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("extraction_id", sa.String(length=32), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("request_signature", sa.String(length=128), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("downstream_record_id", sa.String(length=100), nullable=True),
        sa.Column("retryable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["operation_id"], ["export_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["extraction_id"], ["extraction_results.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "idempotency_key", "attempt_number", name="uq_export_attempt_record"),
    )
    op.create_index("ix_export_attempt_records_operation_id", "export_attempt_records", ["operation_id"], unique=False)
    op.create_index("ix_export_attempt_records_case_id", "export_attempt_records", ["case_id"], unique=False)
    op.create_index("ix_export_attempt_records_extraction_id", "export_attempt_records", ["extraction_id"], unique=False)
    op.create_index("ix_export_attempt_records_idempotency_key", "export_attempt_records", ["idempotency_key"], unique=False)
    op.create_index("ix_export_attempt_records_status", "export_attempt_records", ["status"], unique=False)
    op.add_column("eval_runs", sa.Column("routing_macro_f1", sa.Float(), nullable=False, server_default="0"))
    op.add_column("eval_runs", sa.Column("field_macro_f1", sa.Float(), nullable=False, server_default="0"))
    op.add_column("eval_runs", sa.Column("false_ready_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("eval_runs", sa.Column("evidence_validity", sa.Float(), nullable=False, server_default="1"))
    op.add_column("eval_runs", sa.Column("category_metrics", sa.JSON(), nullable=True))
    op.add_column("eval_case_results", sa.Column("category", sa.String(length=50), nullable=False, server_default="unknown"))
    op.add_column("eval_case_results", sa.Column("evidence_valid", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("eval_case_results", "evidence_valid")
    op.drop_column("eval_case_results", "category")
    op.drop_index("ix_export_attempt_records_status", table_name="export_attempt_records")
    op.drop_index("ix_export_attempt_records_idempotency_key", table_name="export_attempt_records")
    op.drop_index("ix_export_attempt_records_extraction_id", table_name="export_attempt_records")
    op.drop_index("ix_export_attempt_records_case_id", table_name="export_attempt_records")
    op.drop_index("ix_export_attempt_records_operation_id", table_name="export_attempt_records")
    op.drop_table("export_attempt_records")
    op.drop_column("eval_runs", "category_metrics")
    op.drop_column("eval_runs", "evidence_validity")
    op.drop_column("eval_runs", "false_ready_count")
    op.drop_column("eval_runs", "field_macro_f1")
    op.drop_column("eval_runs", "routing_macro_f1")
    op.drop_column("export_attempts", "retryable")
    op.drop_column("export_attempts", "downstream_record_id")
    op.drop_column("export_attempts", "request_signature")
    op.drop_column("processing_jobs", "failure_classification")
    op.drop_column("processing_jobs", "progress")
    op.drop_column("processing_jobs", "stage")

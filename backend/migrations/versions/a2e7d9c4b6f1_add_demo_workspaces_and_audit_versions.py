"""add isolated demo workspaces and immutable workflow versions

Revision ID: a2e7d9c4b6f1
Revises: 7f3c1a9d5e21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2e7d9c4b6f1"
down_revision: str | Sequence[str] | None = "7f3c1a9d5e21"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_workspaces",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scenario_version", sa.String(length=30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_demo_workspaces_token_hash", "demo_workspaces", ["token_hash"], unique=True)
    op.create_index("ix_demo_workspaces_expires_at", "demo_workspaces", ["expires_at"], unique=False)
    op.add_column("intake_cases", sa.Column("workspace_id", sa.String(length=32), nullable=True))
    op.add_column("intake_cases", sa.Column("scenario", sa.String(length=60), nullable=True))
    op.create_index("ix_intake_cases_workspace_id", "intake_cases", ["workspace_id"], unique=False)
    op.create_index("ix_intake_cases_scenario", "intake_cases", ["scenario"], unique=False)
    with op.batch_alter_table("intake_cases") as batch_op:
        batch_op.create_foreign_key(
            "fk_intake_cases_workspace_id_demo_workspaces",
            "demo_workspaces",
            ["workspace_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.add_column("extraction_results", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("extraction_results", sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_index("ix_extraction_results_is_current", "extraction_results", ["is_current"], unique=False)
    with op.batch_alter_table("extraction_results") as batch_op:
        batch_op.create_unique_constraint(
            "uq_extraction_case_version", ["case_id", "version"]
        )
    op.add_column("validation_issues", sa.Column("extraction_id", sa.String(length=32), nullable=True))
    op.add_column("validation_issues", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_validation_issues_extraction_id", "validation_issues", ["extraction_id"], unique=False)
    with op.batch_alter_table("validation_issues") as batch_op:
        batch_op.create_foreign_key(
            "fk_validation_issues_extraction_id_extraction_results",
            "extraction_results",
            ["extraction_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.add_column("review_decisions", sa.Column("extraction_id", sa.String(length=32), nullable=True))
    op.create_index("ix_review_decisions_extraction_id", "review_decisions", ["extraction_id"], unique=False)
    with op.batch_alter_table("review_decisions") as batch_op:
        batch_op.create_foreign_key(
            "fk_review_decisions_extraction_id_extraction_results",
            "extraction_results",
            ["extraction_id"],
            ["id"],
            ondelete="CASCADE",
        )
    op.create_table(
        "export_attempts",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("extraction_id", sa.String(length=32), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["extraction_id"], ["extraction_results.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "idempotency_key", name="uq_export_attempt_key"),
    )
    op.create_index("ix_export_attempts_case_id", "export_attempts", ["case_id"], unique=False)
    op.create_index("ix_export_attempts_extraction_id", "export_attempts", ["extraction_id"], unique=False)
    op.create_index("ix_export_attempts_status", "export_attempts", ["status"], unique=False)
    op.create_table(
        "model_comparisons",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("case_id", sa.String(length=32), nullable=False),
        sa.Column("cache_key", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["demo_workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["intake_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "cache_key", name="uq_model_comparison_cache"),
    )
    op.create_index("ix_model_comparisons_workspace_id", "model_comparisons", ["workspace_id"], unique=False)
    op.create_index("ix_model_comparisons_case_id", "model_comparisons", ["case_id"], unique=False)
    op.create_index("ix_model_comparisons_cache_key", "model_comparisons", ["cache_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_model_comparisons_cache_key", table_name="model_comparisons")
    op.drop_index("ix_model_comparisons_case_id", table_name="model_comparisons")
    op.drop_index("ix_model_comparisons_workspace_id", table_name="model_comparisons")
    op.drop_table("model_comparisons")
    op.drop_index("ix_export_attempts_status", table_name="export_attempts")
    op.drop_index("ix_export_attempts_extraction_id", table_name="export_attempts")
    op.drop_index("ix_export_attempts_case_id", table_name="export_attempts")
    op.drop_table("export_attempts")
    with op.batch_alter_table("review_decisions") as batch_op:
        batch_op.drop_constraint(
            "fk_review_decisions_extraction_id_extraction_results", type_="foreignkey"
        )
    op.drop_index("ix_review_decisions_extraction_id", table_name="review_decisions")
    op.drop_column("review_decisions", "extraction_id")
    with op.batch_alter_table("validation_issues") as batch_op:
        batch_op.drop_constraint(
            "fk_validation_issues_extraction_id_extraction_results", type_="foreignkey"
        )
    op.drop_index("ix_validation_issues_extraction_id", table_name="validation_issues")
    op.drop_column("validation_issues", "resolved_at")
    op.drop_column("validation_issues", "extraction_id")
    op.drop_index("ix_extraction_results_is_current", table_name="extraction_results")
    with op.batch_alter_table("extraction_results") as batch_op:
        batch_op.drop_constraint("uq_extraction_case_version", type_="unique")
    op.drop_column("extraction_results", "is_current")
    op.drop_column("extraction_results", "version")
    op.drop_index("ix_intake_cases_scenario", table_name="intake_cases")
    op.drop_index("ix_intake_cases_workspace_id", table_name="intake_cases")
    with op.batch_alter_table("intake_cases") as batch_op:
        batch_op.drop_constraint(
            "fk_intake_cases_workspace_id_demo_workspaces", type_="foreignkey"
        )
    op.drop_column("intake_cases", "scenario")
    op.drop_column("intake_cases", "workspace_id")
    op.drop_index("ix_demo_workspaces_expires_at", table_name="demo_workspaces")
    op.drop_index("ix_demo_workspaces_token_hash", table_name="demo_workspaces")
    op.drop_table("demo_workspaces")

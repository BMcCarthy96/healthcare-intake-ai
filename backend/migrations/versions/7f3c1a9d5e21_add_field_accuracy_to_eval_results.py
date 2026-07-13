"""add field accuracy to eval results

Revision ID: 7f3c1a9d5e21
Revises: 2bebefca9627
Create Date: 2026-07-12 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '7f3c1a9d5e21'
down_revision: str | Sequence[str] | None = '2bebefca9627'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'eval_runs',
        sa.Column('field_accuracy', sa.Float(), nullable=False, server_default='0'),
    )
    op.add_column(
        'eval_case_results',
        sa.Column('fields_matched', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'eval_case_results',
        sa.Column('fields_compared', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('eval_case_results', 'fields_compared')
    op.drop_column('eval_case_results', 'fields_matched')
    op.drop_column('eval_runs', 'field_accuracy')

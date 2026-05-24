"""Add ai_call_id to call_analyses for AI call intelligence

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-21

Changes:
1. Add ai_call_id nullable FK column to call_analyses
2. Make human_call_id nullable (analyses can belong to either call type)
3. Drop/recreate unique constraint to only cover non-null values (partial index)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add ai_call_id FK column
    op.add_column(
        "call_analyses",
        sa.Column("ai_call_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "call_analyses_ai_call_id_fkey",
        "call_analyses", "calls",
        ["ai_call_id"], ["id"],
        ondelete="CASCADE",
    )
    # Partial unique index so each AI call has at most one analysis
    op.create_index(
        "uq_analysis_ai_call_id",
        "call_analyses",
        ["ai_call_id"],
        unique=True,
        postgresql_where=sa.text("ai_call_id IS NOT NULL"),
    )

    # Make human_call_id nullable so rows can be AI-only
    op.alter_column("call_analyses", "human_call_id", nullable=True)


def downgrade() -> None:
    op.drop_index("uq_analysis_ai_call_id", table_name="call_analyses")
    op.drop_constraint("call_analyses_ai_call_id_fkey", "call_analyses", type_="foreignkey")
    op.drop_column("call_analyses", "ai_call_id")
    op.alter_column("call_analyses", "human_call_id", nullable=False)

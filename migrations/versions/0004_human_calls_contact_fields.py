"""Add contact fields to human_calls; make borrower_id nullable

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-19

Changes:
1. Add contact_name, contact_phone, amount_due, days_overdue to human_calls
2. Make human_calls.borrower_id nullable (calls are standalone, no borrower required)
3. Make call_analyses.borrower_id nullable
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── human_calls: add contact fields ───────────────────────────────────────
    op.add_column("human_calls", sa.Column("contact_name", sa.String(200), nullable=True))
    op.add_column("human_calls", sa.Column("contact_phone", sa.String(30), nullable=True))
    op.add_column("human_calls", sa.Column("amount_due", sa.Numeric(12, 2), nullable=True))
    op.add_column("human_calls", sa.Column("days_overdue", sa.Integer(), nullable=True))

    # Make borrower_id optional (calls no longer require a DB borrower record)
    op.alter_column("human_calls", "borrower_id", nullable=True)

    # Drop the FK constraint so NULL is allowed without FK violation
    op.drop_constraint("human_calls_borrower_id_fkey", "human_calls", type_="foreignkey")
    op.create_foreign_key(
        "human_calls_borrower_id_fkey",
        "human_calls", "borrowers",
        ["borrower_id"], ["id"],
        ondelete="SET NULL",
    )

    # ── call_analyses: make borrower_id nullable ───────────────────────────────
    op.alter_column("call_analyses", "borrower_id", nullable=True)
    op.drop_constraint("call_analyses_borrower_id_fkey", "call_analyses", type_="foreignkey")
    op.create_foreign_key(
        "call_analyses_borrower_id_fkey",
        "call_analyses", "borrowers",
        ["borrower_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_column("human_calls", "contact_name")
    op.drop_column("human_calls", "contact_phone")
    op.drop_column("human_calls", "amount_due")
    op.drop_column("human_calls", "days_overdue")

    op.drop_constraint("human_calls_borrower_id_fkey", "human_calls", type_="foreignkey")
    op.create_foreign_key(
        "human_calls_borrower_id_fkey",
        "human_calls", "borrowers",
        ["borrower_id"], ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("human_calls", "borrower_id", nullable=False)

    op.drop_constraint("call_analyses_borrower_id_fkey", "call_analyses", type_="foreignkey")
    op.create_foreign_key(
        "call_analyses_borrower_id_fkey",
        "call_analyses", "borrowers",
        ["borrower_id"], ["id"],
    )
    op.alter_column("call_analyses", "borrower_id", nullable=False)

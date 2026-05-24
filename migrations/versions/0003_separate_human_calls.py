"""separate human_calls table — remove call_type discriminator from calls

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-19

Changes:
1. Create standalone human_calls table
2. Update call_analyses: swap call_id (FK→calls) for human_call_id (FK→human_calls)
3. Remove call_type / human_agent_id / human_agent_name columns from calls
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create human_calls table ───────────────────────────────────────────
    op.create_table(
        "human_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("borrowers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("human_agent_id", sa.String(128)),
        sa.Column("human_agent_name", sa.String(200)),
        sa.Column("twilio_call_sid", sa.String(100), unique=True),
        sa.Column("status", sa.String(30), server_default="initiated", nullable=False),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("from_number", sa.String(30)),
        sa.Column("to_number", sa.String(30)),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_human_calls_borrower", "human_calls", ["borrower_id"])
    op.create_index("idx_human_calls_status", "human_calls", ["status"])

    op.execute("""
        CREATE TRIGGER trg_human_calls_updated_at
            BEFORE UPDATE ON human_calls
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)

    # ── 2. Update call_analyses: swap call_id → human_call_id ─────────────────
    # Drop old unique constraint and index on call_id
    op.drop_constraint("uq_analysis_call_id", "call_analyses", type_="unique")
    op.drop_index("idx_call_analyses_call", table_name="call_analyses")

    # Add human_call_id column (nullable first for safety)
    op.add_column("call_analyses", sa.Column(
        "human_call_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("human_calls.id", ondelete="CASCADE"),
        nullable=True,
    ))

    # Drop old call_id FK + column
    op.drop_constraint("call_analyses_call_id_fkey", "call_analyses", type_="foreignkey")
    op.drop_column("call_analyses", "call_id")

    # Make human_call_id NOT NULL and add unique constraint
    op.alter_column("call_analyses", "human_call_id", nullable=False)
    op.create_unique_constraint("uq_analysis_human_call_id", "call_analyses", ["human_call_id"])
    op.create_index("idx_call_analyses_human_call", "call_analyses", ["human_call_id"])

    # ── 3. Remove human-agent columns from calls ──────────────────────────────
    op.drop_index("idx_calls_type", table_name="calls")
    op.drop_column("calls", "call_type")
    op.drop_column("calls", "human_agent_id")
    op.drop_column("calls", "human_agent_name")


def downgrade() -> None:
    # Restore calls columns
    op.add_column("calls", sa.Column("call_type", sa.String(20), server_default="ai_agent", nullable=False))
    op.add_column("calls", sa.Column("human_agent_id", sa.String(128)))
    op.add_column("calls", sa.Column("human_agent_name", sa.String(200)))
    op.create_index("idx_calls_type", "calls", ["call_type"])

    # Restore call_analyses.call_id
    op.drop_index("idx_call_analyses_human_call", table_name="call_analyses")
    op.drop_constraint("uq_analysis_human_call_id", "call_analyses", type_="unique")
    op.add_column("call_analyses", sa.Column(
        "call_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("calls.id", ondelete="CASCADE"),
        nullable=True,
    ))
    op.drop_constraint("call_analyses_human_call_id_fkey", "call_analyses", type_="foreignkey")
    op.drop_column("call_analyses", "human_call_id")
    op.create_unique_constraint("uq_analysis_call_id", "call_analyses", ["call_id"])
    op.create_index("idx_call_analyses_call", "call_analyses", ["call_id"])

    # Drop human_calls
    op.execute("DROP TRIGGER IF EXISTS trg_human_calls_updated_at ON human_calls")
    op.drop_index("idx_human_calls_status", table_name="human_calls")
    op.drop_index("idx_human_calls_borrower", table_name="human_calls")
    op.drop_table("human_calls")

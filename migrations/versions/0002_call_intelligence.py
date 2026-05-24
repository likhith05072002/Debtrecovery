"""call intelligence — human call transcription + analysis tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-18

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Add call_type columns to calls ────────────────────────────────────────
    op.add_column("calls", sa.Column("call_type", sa.String(20), server_default="ai_agent", nullable=False))
    op.add_column("calls", sa.Column("human_agent_id", sa.String(128)))
    op.add_column("calls", sa.Column("human_agent_name", sa.String(200)))
    op.create_index("idx_calls_type", "calls", ["call_type"])

    # ── call_analyses ─────────────────────────────────────────────────────────
    op.create_table(
        "call_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("borrowers.id"), nullable=False),

        # Transcript
        sa.Column("transcript_raw", sa.Text()),
        sa.Column("transcript_text", sa.Text()),
        sa.Column("transcript_speakers", postgresql.JSONB(), server_default="[]"),
        sa.Column("transcription_model", sa.String(50)),
        sa.Column("transcription_status", sa.String(20), server_default="pending"),

        # GPT-4o intelligence
        sa.Column("overall_sentiment", sa.String(20)),
        sa.Column("sentiment_score", sa.Numeric(4, 3)),
        sa.Column("willingness_to_pay", sa.String(20)),
        sa.Column("payment_intent_score", sa.Numeric(4, 3)),
        sa.Column("key_points", postgresql.JSONB(), server_default="[]"),
        sa.Column("borrower_characterization", sa.Text()),
        sa.Column("repayment_probability", sa.Numeric(4, 3)),
        sa.Column("repayment_probability_reason", sa.Text()),
        sa.Column("recommended_strategy", sa.String(30)),
        sa.Column("next_call_talking_points", postgresql.JSONB(), server_default="[]"),
        sa.Column("analysis_model", sa.String(50)),
        sa.Column("analysis_status", sa.String(20), server_default="pending"),
        sa.Column("analysis_error", sa.Text()),

        # Processing timestamps
        sa.Column("transcription_started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("transcription_completed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("analysis_started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("analysis_completed_at", sa.TIMESTAMP(timezone=True)),

        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),

        sa.UniqueConstraint("call_id", name="uq_analysis_call_id"),
    )
    op.create_index("idx_call_analyses_borrower", "call_analyses", ["borrower_id", sa.text("created_at DESC")])
    op.create_index("idx_call_analyses_call", "call_analyses", ["call_id"])
    op.create_index(
        "idx_call_analyses_pending", "call_analyses", ["analysis_status"],
        postgresql_where=sa.text("analysis_status != 'completed'"),
    )

    # updated_at trigger for call_analyses
    op.execute("""
        CREATE TRIGGER trg_call_analyses_updated_at
            BEFORE UPDATE ON call_analyses
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_call_analyses_updated_at ON call_analyses")
    op.drop_index("idx_call_analyses_pending", table_name="call_analyses")
    op.drop_index("idx_call_analyses_call", table_name="call_analyses")
    op.drop_index("idx_call_analyses_borrower", table_name="call_analyses")
    op.drop_table("call_analyses")

    op.drop_index("idx_calls_type", table_name="calls")
    op.drop_column("calls", "human_agent_name")
    op.drop_column("calls", "human_agent_id")
    op.drop_column("calls", "call_type")

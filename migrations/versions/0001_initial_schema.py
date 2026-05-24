"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-16

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extensions ────────────────────────────────────────────────────────────
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # ── borrowers ─────────────────────────────────────────────────────────────
    op.create_table(
        "borrowers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("external_id", sa.String(128), nullable=False, unique=True),
        sa.Column("phone_e164", sa.String(20), nullable=False),         # AES-256 encrypted
        sa.Column("phone_hash", sa.String(64), nullable=False),         # SHA-256 for lookups
        sa.Column("first_name", sa.String(100)),
        sa.Column("last_name", sa.String(100)),
        sa.Column("email_hash", sa.String(64)),
        sa.Column("time_zone", sa.String(64), server_default="America/New_York"),
        sa.Column("preferred_language", sa.String(10), server_default="en"),
        # Debt info
        sa.Column("original_creditor", sa.String(200)),
        sa.Column("account_number_hash", sa.String(64)),
        sa.Column("principal_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("current_balance", sa.Numeric(12, 2), nullable=False),
        sa.Column("interest_rate", sa.Numeric(5, 4)),
        sa.Column("days_past_due", sa.Integer(), server_default="0"),
        sa.Column("debt_type", sa.String(50)),
        # Compliance flags
        sa.Column("do_not_call", sa.Boolean(), server_default="false"),
        sa.Column("opted_out", sa.Boolean(), server_default="false"),
        sa.Column("opted_out_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("bankruptcy_filed", sa.Boolean(), server_default="false"),
        sa.Column("deceased", sa.Boolean(), server_default="false"),
        sa.Column("consent_recorded", sa.Boolean(), server_default="false"),
        sa.Column("consent_recorded_at", sa.TIMESTAMP(timezone=True)),
        # Behavioral profile
        sa.Column("engagement_score", sa.Numeric(4, 3), server_default="0.5"),
        sa.Column("repayment_likelihood", sa.Numeric(4, 3), server_default="0.5"),
        sa.Column("sentiment_trend", sa.String(20), server_default="neutral"),
        sa.Column("avoidance_score", sa.Numeric(4, 3), server_default="0.0"),
        sa.Column("promise_kept_rate", sa.Numeric(4, 3)),
        sa.Column("best_call_hour_utc", sa.SmallInteger()),
        sa.Column("best_call_day", sa.SmallInteger()),
        sa.Column("total_calls", sa.Integer(), server_default="0"),
        sa.Column("successful_contacts", sa.Integer(), server_default="0"),
        # Timestamps
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_borrowers_phone_hash", "borrowers", ["phone_hash"])
    op.create_index("idx_borrowers_external_id", "borrowers", ["external_id"])
    op.create_index("idx_borrowers_engagement", "borrowers", [sa.text("engagement_score DESC")])

    # ── campaigns ─────────────────────────────────────────────────────────────
    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("strategy_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft"),
        sa.Column("max_attempts", sa.Integer(), server_default="5"),
        sa.Column("call_window_start", sa.Time(), server_default="09:00:00"),
        sa.Column("call_window_end", sa.Time(), server_default="20:00:00"),
        sa.Column("allowed_days", postgresql.ARRAY(sa.SmallInteger()), server_default="{1,2,3,4,5}"),
        sa.Column("retry_interval_hrs", sa.Numeric(4, 1), server_default="24.0"),
        sa.Column("settlement_floor_pct", sa.Numeric(4, 3), server_default="0.50"),
        sa.Column("script_override", postgresql.JSONB()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )

    # ── campaign_borrowers ────────────────────────────────────────────────────
    op.create_table(
        "campaign_borrowers",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("borrowers.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("priority", sa.SmallInteger(), server_default="5"),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("next_call_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("last_outcome", sa.String(50)),
    )
    op.create_index(
        "idx_cb_next_call", "campaign_borrowers", ["next_call_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ── calls ─────────────────────────────────────────────────────────────────
    op.create_table(
        "calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("twilio_call_sid", sa.String(64), unique=True),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("borrowers.id"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id")),
        sa.Column("direction", sa.String(10), server_default="outbound"),
        sa.Column("from_number", sa.String(20)),
        sa.Column("to_number", sa.String(20)),
        sa.Column("status", sa.String(30), server_default="initiated"),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("answered_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("outcome", sa.String(50)),
        sa.Column("promise_amount", sa.Numeric(12, 2)),
        sa.Column("promise_date", sa.Date()),
        sa.Column("payment_collected", sa.Numeric(12, 2)),
        sa.Column("audio_quality_score", sa.Numeric(4, 3)),
        sa.Column("stt_confidence_avg", sa.Numeric(4, 3)),
        sa.Column("turn_count", sa.Integer(), server_default="0"),
        sa.Column("interruption_count", sa.Integer(), server_default="0"),
        sa.Column("llm_latency_avg_ms", sa.Integer()),
        sa.Column("tts_latency_avg_ms", sa.Integer()),
        sa.Column("stt_latency_avg_ms", sa.Integer()),
        sa.Column("recording_url", sa.Text()),
        sa.Column("recording_consent", sa.Boolean(), server_default="false"),
        sa.Column("fdcpa_violations", postgresql.JSONB(), server_default="[]"),
        sa.Column("compliance_passed", sa.Boolean(), server_default="true"),
        sa.Column("initial_sentiment", sa.String(20)),
        sa.Column("final_sentiment", sa.String(20)),
        sa.Column("sentiment_delta", sa.Numeric(4, 3)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_calls_borrower", "calls", ["borrower_id"])
    op.create_index("idx_calls_campaign", "calls", ["campaign_id"])
    op.create_index("idx_calls_status", "calls", ["status"])
    op.create_index("idx_calls_twilio_sid", "calls", ["twilio_call_sid"])
    op.create_index("idx_calls_started_at", "calls", [sa.text("started_at DESC")])

    # ── conversation_turns ────────────────────────────────────────────────────
    op.create_table(
        "conversation_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_index", sa.SmallInteger(), nullable=False),
        sa.Column("speaker", sa.String(10), nullable=False),
        sa.Column("raw_transcript", sa.Text()),
        sa.Column("normalized_text", sa.Text()),
        sa.Column("stt_confidence", sa.Numeric(4, 3)),
        sa.Column("speech_start_ms", sa.Integer()),
        sa.Column("speech_end_ms", sa.Integer()),
        sa.Column("llm_latency_ms", sa.Integer()),
        sa.Column("tts_latency_ms", sa.Integer()),
        sa.Column("intent", sa.String(100)),
        sa.Column("sentiment_score", sa.Numeric(5, 4)),
        sa.Column("sentiment_label", sa.String(20)),
        sa.Column("entities", postgresql.JSONB(), server_default="{}"),
        sa.Column("barge_in", sa.Boolean(), server_default="false"),
        sa.Column("strategy_used", sa.String(50)),
        sa.Column("function_calls", postgresql.JSONB(), server_default="[]"),
        sa.Column("embedding_id", sa.String(128)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("call_id", "turn_index", name="uq_turn_call_index"),
    )
    op.create_index("idx_turns_call_id", "conversation_turns", ["call_id"])
    op.create_index("idx_turns_intent", "conversation_turns", ["intent"])

    # ── behavioral_events ─────────────────────────────────────────────────────
    op.create_table(
        "behavioral_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("borrowers.id"), nullable=False),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id")),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("event_data", postgresql.JSONB(), server_default="{}"),
        sa.Column("confidence", sa.Numeric(4, 3), server_default="1.0"),
        sa.Column("detected_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_events_borrower", "behavioral_events", ["borrower_id", sa.text("detected_at DESC")])
    op.create_index("idx_events_type", "behavioral_events", ["event_type"])
    op.create_index("idx_events_call", "behavioral_events", ["call_id"])

    # ── repayment_promises ────────────────────────────────────────────────────
    op.create_table(
        "repayment_promises",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("borrowers.id"), nullable=False),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id"), nullable=False),
        sa.Column("promised_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("promised_date", sa.Date(), nullable=False),
        sa.Column("method", sa.String(50)),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("actual_amount", sa.Numeric(12, 2)),
        sa.Column("resolved_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_promises_borrower", "repayment_promises", ["borrower_id"])
    op.create_index(
        "idx_promises_date", "repayment_promises", ["promised_date"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ── compliance_events ─────────────────────────────────────────────────────
    op.create_table(
        "compliance_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("borrowers.id"), nullable=False),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id")),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), server_default="info"),
        sa.Column("description", sa.Text()),
        sa.Column("auto_actioned", sa.Boolean(), server_default="false"),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True)),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_compliance_borrower", "compliance_events", ["borrower_id", sa.text("created_at DESC")])
    op.create_index(
        "idx_compliance_severity", "compliance_events", ["severity"],
        postgresql_where=sa.text("severity = 'violation'"),
    )

    # ── ml_call_outcomes ──────────────────────────────────────────────────────
    op.create_table(
        "ml_call_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("call_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("calls.id"), nullable=False),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("borrowers.id"), nullable=False),
        sa.Column("days_past_due", sa.Integer()),
        sa.Column("balance", sa.Numeric(12, 2)),
        sa.Column("debt_type", sa.String(50)),
        sa.Column("time_of_day_hour", sa.SmallInteger()),
        sa.Column("day_of_week", sa.SmallInteger()),
        sa.Column("previous_attempts", sa.Integer()),
        sa.Column("previous_outcomes", postgresql.ARRAY(sa.Text())),
        sa.Column("avg_sentiment_previous", sa.Numeric(4, 3)),
        sa.Column("avoidance_score", sa.Numeric(4, 3)),
        sa.Column("engagement_score", sa.Numeric(4, 3)),
        sa.Column("strategy_used", sa.String(50)),
        sa.Column("outcome_label", sa.String(50)),
        sa.Column("promise_kept", sa.Boolean()),
        sa.Column("model_version", sa.String(20)),
        sa.Column("split", sa.String(10), server_default="train"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index("idx_ml_outcomes_borrower", "ml_call_outcomes", ["borrower_id"])
    op.create_index("idx_ml_outcomes_label", "ml_call_outcomes", ["outcome_label"])

    # ── call_schedule ─────────────────────────────────────────────────────────
    op.create_table(
        "call_schedule",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("borrower_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("borrowers.id"), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("campaigns.id")),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default="5"),
        sa.Column("attempt_number", sa.Integer(), server_default="1"),
        sa.Column("strategy_hint", sa.String(50)),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("celery_task_id", sa.String(128)),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("NOW()")),
    )
    op.create_index(
        "idx_schedule_next", "call_schedule", ["scheduled_at", "priority"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ── updated_at triggers ───────────────────────────────────────────────────
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
        $$ LANGUAGE plpgsql
    """)
    for table in ("borrowers", "campaigns"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """)


def downgrade() -> None:
    for table in ("borrowers", "campaigns"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column")

    for table in [
        "call_schedule", "ml_call_outcomes", "compliance_events",
        "repayment_promises", "behavioral_events", "conversation_turns",
        "calls", "campaign_borrowers", "campaigns", "borrowers",
    ]:
        op.drop_table(table)

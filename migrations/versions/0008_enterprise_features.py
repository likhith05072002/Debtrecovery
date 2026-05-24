"""Add enterprise features: webhooks, audit_log, scheduled_reports, white_label_config, onboarding

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-05

Changes:
1. Create webhooks table
2. Create webhook_deliveries table
3. Create audit_log table
4. Create scheduled_reports table
5. Create white_label_config table
6. Create onboarding_progress table
7. Create marketplace_templates table
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Webhooks ───────────────────────────────────────────────────────────
    op.create_table(
        "webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("events", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("failure_count", sa.Integer(), server_default="0"),
        sa.Column("last_triggered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_webhooks_org", "webhooks", ["organization_id"])

    # ── 2. Webhook Deliveries ─────────────────────────────────────────────────
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("webhook_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="1"),
        sa.Column("success", sa.Boolean(), server_default="false"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_webhook_deliveries_webhook", "webhook_deliveries", ["webhook_id"])

    # ── 3. Audit Log ─────────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changes", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_audit_log_org_created", "audit_log", ["organization_id", "created_at"])
    op.create_index("ix_audit_log_resource", "audit_log", ["resource_type", "resource_id"])

    # ── 4. Scheduled Reports ──────────────────────────────────────────────────
    op.create_table(
        "scheduled_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("report_type", sa.String(50), nullable=False),
        sa.Column("schedule_cron", sa.String(50), nullable=False),
        sa.Column("recipients", postgresql.JSONB(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=True),
        sa.Column("format", sa.String(10), server_default="'pdf'"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("last_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_scheduled_reports_org", "scheduled_reports", ["organization_id"])

    # ── 5. White-Label Config ─────────────────────────────────────────────────
    op.create_table(
        "white_label_config",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("custom_domain", sa.String(255), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("favicon_url", sa.Text(), nullable=True),
        sa.Column("primary_color", sa.String(7), server_default="'#2563EB'"),
        sa.Column("secondary_color", sa.String(7), server_default="'#1E40AF'"),
        sa.Column("company_name", sa.String(200), nullable=True),
        sa.Column("email_from_name", sa.String(100), nullable=True),
        sa.Column("email_from_address", sa.String(255), nullable=True),
        sa.Column("custom_css", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # ── 6. Onboarding Progress ────────────────────────────────────────────────
    op.create_table(
        "onboarding_progress",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("steps_completed", postgresql.JSONB(), server_default="{}"),
        sa.Column("current_step", sa.String(50), server_default="'phone'"),
        sa.Column("first_call_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("first_collection_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("activation_score", sa.Numeric(4, 3), server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # ── 7. Marketplace Templates ──────────────────────────────────────────────
    op.create_table(
        "marketplace_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("author_org_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("downloads", sa.Integer(), server_default="0"),
        sa.Column("rating", sa.Numeric(3, 2), server_default="0"),
        sa.Column("is_public", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_marketplace_category", "marketplace_templates", ["category"])


def downgrade() -> None:
    op.drop_table("marketplace_templates")
    op.drop_table("onboarding_progress")
    op.drop_table("white_label_config")
    op.drop_table("scheduled_reports")
    op.drop_table("audit_log")
    op.drop_table("webhook_deliveries")
    op.drop_table("webhooks")

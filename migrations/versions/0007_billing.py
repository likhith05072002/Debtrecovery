"""Add billing tables: subscriptions, usage_records, plan_limits, invoices + seed plan data

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-05

Changes:
1. Create subscriptions table
2. Create usage_records table
3. Create plan_limits table
4. Create invoices table
5. Seed starter/growth/enterprise plan limits
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Subscriptions ──────────────────────────────────────────────────────
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("stripe_customer_id", sa.String(64), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(64), nullable=True),
        sa.Column("plan_tier", sa.String(20), nullable=False, server_default="starter"),
        sa.Column("status", sa.String(20), server_default="trialing"),
        sa.Column("trial_ends_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("current_period_start", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # ── 2. Usage Records ──────────────────────────────────────────────────────
    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("ai_call_minutes", sa.Numeric(10, 2), server_default="0"),
        sa.Column("human_call_minutes", sa.Numeric(10, 2), server_default="0"),
        sa.Column("ai_calls_count", sa.Integer(), server_default="0"),
        sa.Column("successful_collections", sa.Numeric(12, 2), server_default="0"),
        sa.Column("api_calls_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_usage_records_org_period",
        "usage_records",
        ["organization_id", "period_start"],
        unique=True,
    )

    # ── 3. Plan Limits ────────────────────────────────────────────────────────
    op.create_table(
        "plan_limits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("tier", sa.String(20), unique=True, nullable=False),
        sa.Column("monthly_ai_minutes", sa.Integer(), nullable=True),
        sa.Column("monthly_calls", sa.Integer(), nullable=True),
        sa.Column("max_borrowers", sa.Integer(), nullable=True),
        sa.Column("max_campaigns", sa.Integer(), nullable=True),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("features", postgresql.JSONB(), server_default="{}"),
        sa.Column("per_minute_rate_cents", sa.Integer(), server_default="50"),
        sa.Column("success_fee_bps", sa.Integer(), server_default="0"),
        sa.Column("base_price_cents", sa.Integer(), server_default="49900"),
    )

    # ── 4. Invoices ───────────────────────────────────────────────────────────
    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stripe_invoice_id", sa.String(64), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("subtotal_cents", sa.Integer(), server_default="0"),
        sa.Column("tax_cents", sa.Integer(), server_default="0"),
        sa.Column("total_cents", sa.Integer(), server_default="0"),
        sa.Column("status", sa.String(20), server_default="'draft'"),
        sa.Column("paid_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("line_items", postgresql.JSONB(), server_default="[]"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_invoices_org", "invoices", ["organization_id"])

    # ── 5. Seed plan limits ───────────────────────────────────────────────────
    op.execute("""
        INSERT INTO plan_limits (id, tier, monthly_ai_minutes, monthly_calls, max_borrowers, max_campaigns, max_users, features, per_minute_rate_cents, success_fee_bps, base_price_cents)
        VALUES
            (gen_random_uuid(), 'starter', 500, 500, 1000, 3, 2, '{"webhooks": false, "custom_voice": false, "api_access": false}', 50, 0, 49900),
            (gen_random_uuid(), 'growth', 5000, 5000, 25000, NULL, 10, '{"webhooks": true, "custom_voice": true, "api_access": true}', 30, 0, 199900),
            (gen_random_uuid(), 'enterprise', NULL, NULL, NULL, NULL, NULL, '{"webhooks": true, "custom_voice": true, "api_access": true, "white_label": true, "sso": true}', 15, 250, 0)
    """)


def downgrade() -> None:
    op.drop_table("invoices")
    op.drop_table("plan_limits")
    op.drop_index("ix_usage_records_org_period", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_table("subscriptions")

"""Add multi-tenancy: organizations, users, api_keys, invitations tables + org_id on all existing tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-05

Changes:
1. Create organizations table
2. Create users table
3. Create api_keys table
4. Create invitations table
5. Add organization_id FK to: borrowers, calls, campaigns, call_analyses,
   compliance_events, human_calls, call_schedule
6. Create default organization and backfill existing rows
7. Add NOT NULL constraint + composite indexes
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# Default org ID for backfilling existing data
DEFAULT_ORG_ID = uuid.uuid4()


def upgrade() -> None:
    # ── 1. Create organizations table ─────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("plan_tier", sa.String(20), server_default="starter"),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("settings", postgresql.JSONB(), server_default="{}"),
        sa.Column("twilio_account_sid", sa.String(64), nullable=True),
        sa.Column("twilio_auth_token_encrypted", sa.Text(), nullable=True),
        sa.Column("twilio_from_numbers", postgresql.JSONB(), server_default="[]"),
        sa.Column("elevenlabs_voice_id", sa.String(64), nullable=True),
        sa.Column("agent_name", sa.String(100), server_default="Alex"),
        sa.Column("agency_name", sa.String(200), server_default="Apex Recovery Services"),
        sa.Column("max_concurrent_calls", sa.Integer(), server_default="5"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # ── 2. Create users table ─────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("role", sa.String(30), nullable=False, server_default="agent"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("email_verified", sa.Boolean(), server_default="false"),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("mfa_enabled", sa.Boolean(), server_default="false"),
        sa.Column("mfa_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])

    # ── 3. Create api_keys table ──────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("key_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("key_prefix", sa.String(8), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("scopes", postgresql.JSONB(), server_default='["*"]'),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_api_keys_organization_id", "api_keys", ["organization_id"])

    # ── 4. Create invitations table ───────────────────────────────────────────
    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(30), nullable=False, server_default="agent"),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # ── 5. Insert default organization for backfill ───────────────────────────
    op.execute(
        f"""
        INSERT INTO organizations (id, name, slug, plan_tier, status)
        VALUES ('{DEFAULT_ORG_ID}', 'Default Organization', 'default', 'enterprise', 'active')
        """
    )

    # ── 6. Add organization_id to existing tables ─────────────────────────────
    tables_to_modify = [
        "borrowers",
        "calls",
        "campaigns",
        "call_analyses",
        "compliance_events",
        "human_calls",
        "call_schedule",
    ]

    for table in tables_to_modify:
        # Add nullable column first
        op.add_column(
            table,
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        # Backfill with default org
        op.execute(f"UPDATE {table} SET organization_id = '{DEFAULT_ORG_ID}'")
        # Set NOT NULL
        op.alter_column(table, "organization_id", nullable=False)
        # Add FK constraint
        op.create_foreign_key(
            f"fk_{table}_organization_id",
            table,
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="CASCADE",
        )
        # Add composite index for tenant-scoped queries
        op.create_index(
            f"ix_{table}_org_created",
            table,
            ["organization_id", "created_at"],
        )


def downgrade() -> None:
    tables_to_modify = [
        "borrowers",
        "calls",
        "campaigns",
        "call_analyses",
        "compliance_events",
        "human_calls",
        "call_schedule",
    ]

    for table in tables_to_modify:
        op.drop_index(f"ix_{table}_org_created", table_name=table)
        op.drop_constraint(f"fk_{table}_organization_id", table, type_="foreignkey")
        op.drop_column(table, "organization_id")

    op.drop_table("invitations")
    op.drop_table("api_keys")
    op.drop_table("users")
    op.drop_table("organizations")

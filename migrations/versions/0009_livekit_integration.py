"""Add LiveKit integration: livekit_room_name column on calls

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-24

Changes:
1. Add livekit_room_name column to calls table (nullable — legacy calls use twilio_call_sid)
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calls", sa.Column("livekit_room_name", sa.String(128), nullable=True))
    op.create_index("ix_calls_livekit_room", "calls", ["livekit_room_name"])


def downgrade() -> None:
    op.drop_index("ix_calls_livekit_room", table_name="calls")
    op.drop_column("calls", "livekit_room_name")

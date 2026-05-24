from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.database.base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    plan_tier: Mapped[str] = mapped_column(String(20), default="starter")  # starter/growth/enterprise
    status: Mapped[str] = mapped_column(String(20), default="active")  # active/suspended/cancelled

    # Org-level settings (call window overrides, language prefs, etc.)
    settings: Mapped[dict | None] = mapped_column(JSONB(), default=dict)

    # Per-org Twilio configuration (subaccount or shared)
    twilio_account_sid: Mapped[str | None] = mapped_column(String(64))
    twilio_auth_token_encrypted: Mapped[str | None] = mapped_column(Text())
    twilio_from_numbers: Mapped[list | None] = mapped_column(JSONB(), default=list)

    # Per-org voice configuration
    elevenlabs_voice_id: Mapped[str | None] = mapped_column(String(64))
    agent_name: Mapped[str] = mapped_column(String(100), default="Alex")
    agency_name: Mapped[str] = mapped_column(String(200), default="Apex Recovery Services")

    # Limits
    max_concurrent_calls: Mapped[int] = mapped_column(Integer(), default=5)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="organization", lazy="select")
    api_keys: Mapped[list["APIKey"]] = relationship("APIKey", back_populates="organization", lazy="select")

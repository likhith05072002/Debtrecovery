"""Onboarding and marketplace models."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.database.base import Base


class OnboardingProgress(Base):
    __tablename__ = "onboarding_progress"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    steps_completed: Mapped[dict] = mapped_column(JSONB(), default=dict)
    # Steps: phone, borrowers, voice, compliance, campaign, first_call
    current_step: Mapped[str] = mapped_column(String(50), default="phone")
    first_call_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    first_collection_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    activation_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0"))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class MarketplaceTemplate(Base):
    __tablename__ = "marketplace_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # script/campaign/compliance_pack
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text())
    config: Mapped[dict] = mapped_column(JSONB(), nullable=False)
    author_org_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # NULL = official
    downloads: Mapped[int] = mapped_column(Integer(), default=0)
    rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0"))
    is_public: Mapped[bool] = mapped_column(Boolean(), default=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

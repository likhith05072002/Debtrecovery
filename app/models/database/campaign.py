from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import Integer, Numeric, SmallInteger, String, Time, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.database.base import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    strategy_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    max_attempts: Mapped[int] = mapped_column(Integer(), default=5)
    call_window_start: Mapped[time] = mapped_column(Time(), default=time(9, 0))
    call_window_end: Mapped[time] = mapped_column(Time(), default=time(20, 0))
    allowed_days: Mapped[list] = mapped_column(ARRAY(SmallInteger()), default=lambda: [1, 2, 3, 4, 5])
    retry_interval_hrs: Mapped[Decimal] = mapped_column(Numeric(4, 1), default=Decimal("24.0"))
    settlement_floor_pct: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.50"))
    script_override: Mapped[dict | None] = mapped_column(JSONB())
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class CampaignBorrower(Base):
    __tablename__ = "campaign_borrowers"

    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    borrower_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("borrowers.id", ondelete="CASCADE"), primary_key=True)
    priority: Mapped[int] = mapped_column(SmallInteger(), default=5)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer(), default=0)
    next_call_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_outcome: Mapped[str | None] = mapped_column(String(50))


class CallSchedule(Base):
    __tablename__ = "call_schedule"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    borrower_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("borrowers.id"), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id"))
    scheduled_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger(), default=5)
    attempt_number: Mapped[int] = mapped_column(Integer(), default=1)
    strategy_hint: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    celery_task_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

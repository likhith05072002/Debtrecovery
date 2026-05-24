from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, SmallInteger, String, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.database.base import Base


class MLCallOutcome(Base):
    __tablename__ = "ml_call_outcomes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id"), nullable=False)
    borrower_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("borrowers.id"), nullable=False)

    # Input features
    days_past_due: Mapped[int | None] = mapped_column(Integer())
    balance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    debt_type: Mapped[str | None] = mapped_column(String(50))
    time_of_day_hour: Mapped[int | None] = mapped_column(SmallInteger())
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger())
    previous_attempts: Mapped[int | None] = mapped_column(Integer())
    previous_outcomes: Mapped[list[str] | None] = mapped_column(ARRAY(Text()))
    avg_sentiment_previous: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    avoidance_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    engagement_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    strategy_used: Mapped[str | None] = mapped_column(String(50))

    # Target labels
    outcome_label: Mapped[str | None] = mapped_column(String(50))
    promise_kept: Mapped[bool | None] = mapped_column(Boolean())

    # Metadata
    model_version: Mapped[str | None] = mapped_column(String(20))
    split: Mapped[str] = mapped_column(String(10), default="train")
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

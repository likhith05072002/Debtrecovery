from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Integer, Numeric, String, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.database.base import Base


class HumanCall(Base):
    __tablename__ = "human_calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    borrower_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("borrowers.id", ondelete="SET NULL"), nullable=True)
    human_agent_id: Mapped[str | None] = mapped_column(String(128))
    human_agent_name: Mapped[str | None] = mapped_column(String(200))
    twilio_call_sid: Mapped[str | None] = mapped_column(String(100), unique=True)

    # Free-form contact info (no borrower DB record required)
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_phone: Mapped[str | None] = mapped_column(String(30))
    amount_due: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    days_overdue: Mapped[int | None] = mapped_column(Integer())

    # Status: initiated | in_progress | completed | failed
    status: Mapped[str] = mapped_column(String(30), default="initiated")

    duration_seconds: Mapped[int | None] = mapped_column(Integer())
    from_number: Mapped[str | None] = mapped_column(String(30))
    to_number: Mapped[str | None] = mapped_column(String(30))

    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    borrower: Mapped["Borrower | None"] = relationship("Borrower", back_populates="human_calls")
    analysis: Mapped["CallAnalysis | None"] = relationship("CallAnalysis", back_populates="human_call", uselist=False, lazy="select")

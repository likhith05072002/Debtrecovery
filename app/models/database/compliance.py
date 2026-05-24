from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.database.base import Base


class ComplianceEvent(Base):
    __tablename__ = "compliance_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    borrower_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("borrowers.id"), nullable=False)
    call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id"))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="info")   # info | warning | violation
    description: Mapped[str | None] = mapped_column(Text())
    auto_actioned: Mapped[bool] = mapped_column(Boolean(), default=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    borrower: Mapped["Borrower"] = relationship("Borrower", back_populates="compliance_events")
    call: Mapped["Call | None"] = relationship("Call", back_populates="compliance_events")

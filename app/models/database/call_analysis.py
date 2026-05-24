from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Numeric, String, Text, TIMESTAMP, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.database.base import Base


class CallAnalysis(Base):
    __tablename__ = "call_analyses"
    __table_args__ = (UniqueConstraint("human_call_id", name="uq_analysis_human_call_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    human_call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("human_calls.id", ondelete="CASCADE"), nullable=True)
    ai_call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=True)
    borrower_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("borrowers.id", ondelete="SET NULL"), nullable=True)

    # Transcript
    transcript_raw: Mapped[str | None] = mapped_column(Text())
    transcript_text: Mapped[str | None] = mapped_column(Text())
    transcript_speakers: Mapped[list] = mapped_column(JSONB(), default=list)
    transcription_model: Mapped[str | None] = mapped_column(String(50))
    transcription_status: Mapped[str] = mapped_column(String(20), default="pending")

    # GPT-4o intelligence
    overall_sentiment: Mapped[str | None] = mapped_column(String(20))
    sentiment_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    willingness_to_pay: Mapped[str | None] = mapped_column(String(20))
    payment_intent_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    key_points: Mapped[list] = mapped_column(JSONB(), default=list)
    borrower_characterization: Mapped[str | None] = mapped_column(Text())
    repayment_probability: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    repayment_probability_reason: Mapped[str | None] = mapped_column(Text())
    recommended_strategy: Mapped[str | None] = mapped_column(String(30))
    next_call_talking_points: Mapped[list] = mapped_column(JSONB(), default=list)
    analysis_model: Mapped[str | None] = mapped_column(String(50))
    analysis_status: Mapped[str] = mapped_column(String(20), default="pending")
    analysis_error: Mapped[str | None] = mapped_column(Text())

    # Processing timestamps
    transcription_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    transcription_completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    analysis_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    analysis_completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    human_call: Mapped["HumanCall | None"] = relationship("HumanCall", back_populates="analysis")
    ai_call: Mapped["Call | None"] = relationship("Call", back_populates="analysis")
    borrower: Mapped["Borrower | None"] = relationship("Borrower", back_populates="call_analyses")

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, SmallInteger, String, Text, TIMESTAMP, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.database.base import Base


class ConversationTurn(Base):
    __tablename__ = "conversation_turns"
    __table_args__ = (UniqueConstraint("call_id", "turn_index", name="uq_turn_call_index"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False)
    turn_index: Mapped[int] = mapped_column(SmallInteger(), nullable=False)
    speaker: Mapped[str] = mapped_column(String(10), nullable=False)   # 'agent' | 'borrower'

    # Content
    raw_transcript: Mapped[str | None] = mapped_column(Text())
    normalized_text: Mapped[str | None] = mapped_column(Text())
    stt_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))

    # Timing (milliseconds from call start)
    speech_start_ms: Mapped[int | None] = mapped_column(Integer())
    speech_end_ms: Mapped[int | None] = mapped_column(Integer())
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer())
    tts_latency_ms: Mapped[int | None] = mapped_column(Integer())

    # Analysis
    intent: Mapped[str | None] = mapped_column(String(100))
    sentiment_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))   # -1.0 to 1.0
    sentiment_label: Mapped[str | None] = mapped_column(String(20))
    entities: Mapped[dict] = mapped_column(JSONB(), default=dict)
    barge_in: Mapped[bool] = mapped_column(Boolean(), default=False)

    # LLM context
    strategy_used: Mapped[str | None] = mapped_column(String(50))
    function_calls: Mapped[list] = mapped_column(JSONB(), default=list)
    embedding_id: Mapped[str | None] = mapped_column(String(128))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    call: Mapped["Call"] = relationship("Call", back_populates="turns")


class BehavioralEvent(Base):
    __tablename__ = "behavioral_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    borrower_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("borrowers.id"), nullable=False)
    call_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id"))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    event_data: Mapped[dict] = mapped_column(JSONB(), default=dict)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("1.0"))
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    borrower: Mapped["Borrower"] = relationship("Borrower", back_populates="behavioral_events")
    call: Mapped["Call | None"] = relationship("Call", back_populates="behavioral_events")


class RepaymentPromise(Base):
    __tablename__ = "repayment_promises"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    borrower_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("borrowers.id"), nullable=False)
    call_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("calls.id"), nullable=False)
    promised_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    promised_date: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    method: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    actual_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    resolved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    borrower: Mapped["Borrower"] = relationship("Borrower", back_populates="repayment_promises")
    call: Mapped["Call"] = relationship("Call", back_populates="repayment_promises")

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, Integer, Numeric, SmallInteger, String, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.database.base import Base


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    twilio_call_sid: Mapped[str | None] = mapped_column(String(64), unique=True)
    livekit_room_name: Mapped[str | None] = mapped_column(String(128))  # LiveKit room for this call
    borrower_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("borrowers.id"), nullable=False)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id"))
    direction: Mapped[str] = mapped_column(String(10), default="outbound")
    from_number: Mapped[str | None] = mapped_column(String(20))
    to_number: Mapped[str | None] = mapped_column(String(20))

    # Status lifecycle
    status: Mapped[str] = mapped_column(String(30), default="initiated")

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    duration_seconds: Mapped[int | None] = mapped_column(Integer())

    # Outcome
    outcome: Mapped[str | None] = mapped_column(String(50))
    promise_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    promise_date: Mapped[date | None] = mapped_column(Date())
    payment_collected: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    # Quality metrics
    audio_quality_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    stt_confidence_avg: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    turn_count: Mapped[int] = mapped_column(Integer(), default=0)
    interruption_count: Mapped[int] = mapped_column(Integer(), default=0)

    # Latency metrics (milliseconds, averages per call)
    llm_latency_avg_ms: Mapped[int | None] = mapped_column(Integer())
    tts_latency_avg_ms: Mapped[int | None] = mapped_column(Integer())
    stt_latency_avg_ms: Mapped[int | None] = mapped_column(Integer())

    # Recording
    recording_url: Mapped[str | None] = mapped_column(Text())
    recording_consent: Mapped[bool] = mapped_column(Boolean(), default=False)

    # Compliance
    fdcpa_violations: Mapped[list] = mapped_column(JSONB(), default=list)
    compliance_passed: Mapped[bool] = mapped_column(Boolean(), default=True)

    # Sentiment trajectory
    initial_sentiment: Mapped[str | None] = mapped_column(String(20))
    final_sentiment: Mapped[str | None] = mapped_column(String(20))
    sentiment_delta: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))

    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationships
    borrower: Mapped["Borrower"] = relationship("Borrower", back_populates="calls")
    analysis: Mapped["CallAnalysis | None"] = relationship("CallAnalysis", back_populates="ai_call", uselist=False, lazy="select")
    turns: Mapped[list["ConversationTurn"]] = relationship("ConversationTurn", back_populates="call", order_by="ConversationTurn.turn_index", lazy="select")
    behavioral_events: Mapped[list["BehavioralEvent"]] = relationship("BehavioralEvent", back_populates="call", lazy="select")
    repayment_promises: Mapped[list["RepaymentPromise"]] = relationship("RepaymentPromise", back_populates="call", lazy="select")
    compliance_events: Mapped[list["ComplianceEvent"]] = relationship("ComplianceEvent", back_populates="call", lazy="select")

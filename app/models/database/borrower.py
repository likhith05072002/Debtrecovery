from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, SmallInteger, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.database.base import Base


class Borrower(Base):
    __tablename__ = "borrowers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    phone_e164: Mapped[str] = mapped_column(String(255), nullable=False)       # AES-256 encrypted (Fernet ~100 chars)
    phone_hash: Mapped[str] = mapped_column(String(64), nullable=False)        # SHA-256
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    email_hash: Mapped[str | None] = mapped_column(String(64))
    time_zone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")

    # Debt info
    original_creditor: Mapped[str | None] = mapped_column(String(200))
    account_number_hash: Mapped[str | None] = mapped_column(String(64))
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    current_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    interest_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    days_past_due: Mapped[int] = mapped_column(Integer(), default=0)
    debt_type: Mapped[str | None] = mapped_column(String(50))

    # Compliance flags
    do_not_call: Mapped[bool] = mapped_column(Boolean(), default=False)
    opted_out: Mapped[bool] = mapped_column(Boolean(), default=False)
    opted_out_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    bankruptcy_filed: Mapped[bool] = mapped_column(Boolean(), default=False)
    deceased: Mapped[bool] = mapped_column(Boolean(), default=False)
    consent_recorded: Mapped[bool] = mapped_column(Boolean(), default=False)
    consent_recorded_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    # Behavioral profile (denormalized for fast reads)
    engagement_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.5"))
    repayment_likelihood: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.5"))
    sentiment_trend: Mapped[str] = mapped_column(String(20), default="neutral")
    avoidance_score: Mapped[Decimal] = mapped_column(Numeric(4, 3), default=Decimal("0.0"))
    promise_kept_rate: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    best_call_hour_utc: Mapped[int | None] = mapped_column(SmallInteger())
    best_call_day: Mapped[int | None] = mapped_column(SmallInteger())
    total_calls: Mapped[int] = mapped_column(Integer(), default=0)
    successful_contacts: Mapped[int] = mapped_column(Integer(), default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    calls: Mapped[list["Call"]] = relationship("Call", back_populates="borrower", lazy="select")
    human_calls: Mapped[list["HumanCall"]] = relationship("HumanCall", back_populates="borrower", lazy="select")
    behavioral_events: Mapped[list["BehavioralEvent"]] = relationship("BehavioralEvent", back_populates="borrower", lazy="select")
    repayment_promises: Mapped[list["RepaymentPromise"]] = relationship("RepaymentPromise", back_populates="borrower", lazy="select")
    compliance_events: Mapped[list["ComplianceEvent"]] = relationship("ComplianceEvent", back_populates="borrower", lazy="select")
    call_analyses: Mapped[list["CallAnalysis"]] = relationship("CallAnalysis", back_populates="borrower", lazy="select")

    @property
    def full_name(self) -> str:
        parts = [p for p in [self.first_name, self.last_name] if p]
        return " ".join(parts) if parts else "Unknown"

    @property
    def is_contactable(self) -> bool:
        return not (self.do_not_call or self.opted_out or self.bankruptcy_filed or self.deceased)

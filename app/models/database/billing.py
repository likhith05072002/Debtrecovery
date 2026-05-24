"""Billing models: subscriptions, usage tracking, plan limits, invoices."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, Integer, Numeric, String, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.database.base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64))
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(64))
    plan_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="starter")
    status: Mapped[str] = mapped_column(String(20), default="trialing")  # trialing/active/past_due/cancelled
    trial_ends_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    current_period_start: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean(), default=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        # One record per org per day
        {"schema": None},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date(), nullable=False)
    period_end: Mapped[date] = mapped_column(Date(), nullable=False)

    # Usage metrics
    ai_call_minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    human_call_minutes: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    ai_calls_count: Mapped[int] = mapped_column(Integer(), default=0)
    successful_collections: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    api_calls_count: Mapped[int] = mapped_column(Integer(), default=0)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class PlanLimit(Base):
    __tablename__ = "plan_limits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tier: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)

    # Included limits
    monthly_ai_minutes: Mapped[int | None] = mapped_column(Integer())  # NULL = unlimited
    monthly_calls: Mapped[int | None] = mapped_column(Integer())
    max_borrowers: Mapped[int | None] = mapped_column(Integer())
    max_campaigns: Mapped[int | None] = mapped_column(Integer())
    max_users: Mapped[int | None] = mapped_column(Integer())

    # Feature flags
    features: Mapped[dict | None] = mapped_column(JSONB(), default=dict)

    # Pricing
    per_minute_rate_cents: Mapped[int] = mapped_column(Integer(), default=50)  # overage rate
    success_fee_bps: Mapped[int] = mapped_column(Integer(), default=0)  # basis points (250 = 2.5%)
    base_price_cents: Mapped[int] = mapped_column(Integer(), default=49900)  # monthly platform fee


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stripe_invoice_id: Mapped[str | None] = mapped_column(String(64))
    period_start: Mapped[date | None] = mapped_column(Date())
    period_end: Mapped[date | None] = mapped_column(Date())
    subtotal_cents: Mapped[int] = mapped_column(Integer(), default=0)
    tax_cents: Mapped[int] = mapped_column(Integer(), default=0)
    total_cents: Mapped[int] = mapped_column(Integer(), default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft/open/paid/void
    paid_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    line_items: Mapped[list | None] = mapped_column(JSONB(), default=list)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())

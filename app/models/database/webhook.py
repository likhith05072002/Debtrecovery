"""Webhook and audit log models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.database.base import Base


class Webhook(Base):
    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(Text(), nullable=False)
    secret: Mapped[str] = mapped_column(Text(), nullable=False)  # HMAC signing secret
    events: Mapped[list] = mapped_column(JSONB(), nullable=False)  # ["call.completed", "payment.promised", ...]
    description: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    failure_count: Mapped[int] = mapped_column(Integer(), default=0)
    last_triggered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    last_status_code: Mapped[int | None] = mapped_column(Integer())

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB(), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer())
    response_body: Mapped[str | None] = mapped_column(Text())
    duration_ms: Mapped[int | None] = mapped_column(Integer())
    attempt: Mapped[int] = mapped_column(Integer(), default=1)
    success: Mapped[bool] = mapped_column(Boolean(), default=False)
    error_message: Mapped[str | None] = mapped_column(Text())

    # Timestamps
    delivered_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "borrower.created", "campaign.started"
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "borrower", "campaign"
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    changes: Mapped[dict | None] = mapped_column(JSONB())  # {field: {old: x, new: y}}
    metadata: Mapped[dict | None] = mapped_column(JSONB())  # extra context
    ip_address: Mapped[str | None] = mapped_column(String(45))  # IPv4 or IPv6
    user_agent: Mapped[str | None] = mapped_column(Text())

    # Timestamps — immutable, append-only
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class ScheduledReport(Base):
    __tablename__ = "scheduled_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    report_type: Mapped[str] = mapped_column(String(50), nullable=False)  # collection_summary, compliance, campaign_perf
    schedule_cron: Mapped[str] = mapped_column(String(50), nullable=False)  # "0 8 * * 1" (Monday 8am)
    recipients: Mapped[list] = mapped_column(JSONB(), nullable=False)  # email list
    filters: Mapped[dict | None] = mapped_column(JSONB())  # custom filters
    format: Mapped[str] = mapped_column(String(10), default="pdf")  # pdf/csv/xlsx
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    last_sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())


class WhiteLabelConfig(Base):
    __tablename__ = "white_label_config"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    custom_domain: Mapped[str | None] = mapped_column(String(255))
    logo_url: Mapped[str | None] = mapped_column(Text())
    favicon_url: Mapped[str | None] = mapped_column(Text())
    primary_color: Mapped[str] = mapped_column(String(7), default="#2563EB")  # hex
    secondary_color: Mapped[str] = mapped_column(String(7), default="#1E40AF")
    company_name: Mapped[str | None] = mapped_column(String(200))
    email_from_name: Mapped[str | None] = mapped_column(String(100))
    email_from_address: Mapped[str | None] = mapped_column(String(255))
    custom_css: Mapped[str | None] = mapped_column(Text())

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())

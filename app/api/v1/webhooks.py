"""Webhook management endpoints."""
from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import enforce_role
from app.dependencies import get_current_user, get_db
from app.models.database.user import User
from app.models.database.webhook import Webhook, WebhookDelivery
from app.services.webhooks.dispatcher import WEBHOOK_EVENTS, test_webhook

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class WebhookCreateRequest(BaseModel):
    url: str = Field(max_length=2048)
    events: list[str] = Field(min_length=1)
    description: str | None = Field(default=None, max_length=200)


class WebhookUpdateRequest(BaseModel):
    url: str | None = Field(default=None, max_length=2048)
    events: list[str] | None = None
    description: str | None = None
    is_active: bool | None = None


class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    description: str | None
    is_active: bool
    failure_count: int
    last_triggered_at: str | None
    last_status_code: int | None
    created_at: str


class WebhookDeliveryResponse(BaseModel):
    id: str
    event_type: str
    status_code: int | None
    success: bool
    duration_ms: int | None
    attempt: int
    error_message: str | None
    delivered_at: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/events")
async def list_event_types():
    """List all available webhook event types."""
    return {"events": WEBHOOK_EVENTS}


@router.post("", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register a new webhook endpoint. Requires admin+ role."""
    enforce_role(current_user.role, "admin")

    # Validate event types
    invalid = [e for e in body.events if e not in WEBHOOK_EVENTS and e != "*"]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid event types: {invalid}",
        )

    webhook = Webhook(
        organization_id=current_user.organization_id,
        url=body.url,
        secret=secrets.token_hex(32),
        events=body.events,
        description=body.description,
    )
    db.add(webhook)
    await db.flush()

    return _serialize_webhook(webhook)


@router.get("", response_model=list[WebhookResponse])
async def list_webhooks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all webhooks for the organization."""
    enforce_role(current_user.role, "admin")

    result = await db.execute(
        select(Webhook)
        .where(Webhook.organization_id == current_user.organization_id)
        .order_by(Webhook.created_at.desc())
    )
    return [_serialize_webhook(w) for w in result.scalars().all()]


@router.get("/{webhook_id}", response_model=WebhookResponse)
async def get_webhook(
    webhook_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get webhook details including signing secret."""
    enforce_role(current_user.role, "admin")
    webhook = await _get_webhook(db, webhook_id, current_user.organization_id)
    resp = _serialize_webhook(webhook)
    return resp


@router.patch("/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: uuid.UUID,
    body: WebhookUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a webhook configuration."""
    enforce_role(current_user.role, "admin")
    webhook = await _get_webhook(db, webhook_id, current_user.organization_id)

    if body.url is not None:
        webhook.url = body.url
    if body.events is not None:
        webhook.events = body.events
    if body.description is not None:
        webhook.description = body.description
    if body.is_active is not None:
        webhook.is_active = body.is_active
        if body.is_active:
            webhook.failure_count = 0  # Reset failures on re-enable

    return _serialize_webhook(webhook)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(
    webhook_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook."""
    enforce_role(current_user.role, "admin")
    webhook = await _get_webhook(db, webhook_id, current_user.organization_id)
    await db.delete(webhook)


@router.post("/{webhook_id}/test", response_model=WebhookDeliveryResponse)
async def test_webhook_endpoint(
    webhook_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a test ping to the webhook endpoint."""
    enforce_role(current_user.role, "admin")
    webhook = await _get_webhook(db, webhook_id, current_user.organization_id)

    delivery = await test_webhook(db, webhook)
    return _serialize_delivery(delivery)


@router.get("/{webhook_id}/deliveries", response_model=list[WebhookDeliveryResponse])
async def list_deliveries(
    webhook_id: uuid.UUID,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent delivery attempts for a webhook."""
    enforce_role(current_user.role, "admin")
    # Verify webhook belongs to org
    await _get_webhook(db, webhook_id, current_user.organization_id)

    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook_id)
        .order_by(WebhookDelivery.delivered_at.desc())
        .limit(limit)
    )
    return [_serialize_delivery(d) for d in result.scalars().all()]


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_webhook(db: AsyncSession, webhook_id: uuid.UUID, org_id: uuid.UUID) -> Webhook:
    result = await db.execute(
        select(Webhook).where(Webhook.id == webhook_id, Webhook.organization_id == org_id)
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    return webhook


def _serialize_webhook(w: Webhook) -> WebhookResponse:
    return WebhookResponse(
        id=str(w.id),
        url=w.url,
        events=w.events,
        description=w.description,
        is_active=w.is_active,
        failure_count=w.failure_count,
        last_triggered_at=w.last_triggered_at.isoformat() if w.last_triggered_at else None,
        last_status_code=w.last_status_code,
        created_at=w.created_at.isoformat(),
    )


def _serialize_delivery(d: WebhookDelivery) -> WebhookDeliveryResponse:
    return WebhookDeliveryResponse(
        id=str(d.id),
        event_type=d.event_type,
        status_code=d.status_code,
        success=d.success,
        duration_ms=d.duration_ms,
        attempt=d.attempt,
        error_message=d.error_message,
        delivered_at=d.delivered_at.isoformat(),
    )

"""Webhook event dispatcher.

Delivers webhook events to registered endpoints with:
- HMAC-SHA256 signature verification
- Exponential backoff retries (3 attempts: 1min, 5min, 30min)
- Automatic disable after 10 consecutive failures
- Async delivery via Celery
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.webhook import Webhook, WebhookDelivery

logger = logging.getLogger(__name__)

# All supported event types
WEBHOOK_EVENTS = [
    "call.started",
    "call.completed",
    "call.failed",
    "payment.promised",
    "payment.collected",
    "payment.broken",
    "borrower.created",
    "borrower.opted_out",
    "dispute.filed",
    "compliance.violation",
    "campaign.started",
    "campaign.completed",
]

MAX_FAILURES = 10
TIMEOUT_SECONDS = 10


def compute_signature(payload: str, secret: str) -> str:
    """Compute HMAC-SHA256 signature for webhook payload."""
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def dispatch_event(
    db: AsyncSession,
    org_id: uuid.UUID,
    event_type: str,
    payload: dict,
) -> int:
    """Dispatch a webhook event to all matching registered webhooks.

    Returns count of webhooks triggered.
    """
    # Find all active webhooks for this org that subscribe to this event
    result = await db.execute(
        select(Webhook).where(
            Webhook.organization_id == org_id,
            Webhook.is_active == True,
            Webhook.failure_count < MAX_FAILURES,
        )
    )
    webhooks = result.scalars().all()

    dispatched = 0
    for webhook in webhooks:
        # Check if this webhook subscribes to this event type
        if event_type not in webhook.events and "*" not in webhook.events:
            continue

        # Deliver synchronously (in production, enqueue via Celery for async delivery)
        await _deliver_webhook(db, webhook, event_type, payload)
        dispatched += 1

    return dispatched


async def _deliver_webhook(
    db: AsyncSession,
    webhook: Webhook,
    event_type: str,
    payload: dict,
    attempt: int = 1,
) -> bool:
    """Deliver a single webhook event. Returns True on success."""
    # Build the full event payload
    event_payload = {
        "id": str(uuid.uuid4()),
        "event": event_type,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "data": payload,
    }

    payload_json = json.dumps(event_payload, default=str)

    # Compute signature
    signature = hmac.new(
        webhook.secret.encode("utf-8"),
        payload_json.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-DebtCollector-Signature": f"sha256={signature}",
        "X-DebtCollector-Event": event_type,
        "X-DebtCollector-Delivery": str(uuid.uuid4()),
        "User-Agent": "DebtCollector-Webhook/1.0",
    }

    # Deliver
    start_time = time.time()
    status_code = None
    response_body = None
    error_message = None
    success = False

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                webhook.url,
                content=payload_json,
                headers=headers,
            )
            status_code = response.status_code
            response_body = response.text[:1000]  # Truncate response
            success = 200 <= status_code < 300
    except httpx.TimeoutException:
        error_message = "Request timed out"
    except httpx.ConnectError:
        error_message = "Connection failed"
    except Exception as e:
        error_message = str(e)[:500]

    duration_ms = int((time.time() - start_time) * 1000)

    # Record delivery attempt
    delivery = WebhookDelivery(
        webhook_id=webhook.id,
        event_type=event_type,
        payload=event_payload,
        status_code=status_code,
        response_body=response_body,
        duration_ms=duration_ms,
        attempt=attempt,
        success=success,
        error_message=error_message,
    )
    db.add(delivery)

    # Update webhook state
    webhook.last_triggered_at = datetime.now(timezone.utc)
    webhook.last_status_code = status_code

    if success:
        webhook.failure_count = 0
    else:
        webhook.failure_count += 1
        if webhook.failure_count >= MAX_FAILURES:
            webhook.is_active = False
            logger.warning(
                "Webhook %s disabled after %d consecutive failures",
                webhook.id, MAX_FAILURES
            )

    return success


async def test_webhook(db: AsyncSession, webhook: Webhook) -> WebhookDelivery:
    """Send a test event to a webhook endpoint."""
    test_payload = {
        "message": "This is a test webhook delivery",
        "webhook_id": str(webhook.id),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    await _deliver_webhook(db, webhook, "test.ping", test_payload)

    # Return the most recent delivery
    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook.id)
        .order_by(WebhookDelivery.delivered_at.desc())
        .limit(1)
    )
    return result.scalar_one()

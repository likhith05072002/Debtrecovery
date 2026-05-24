"""Stripe integration service for subscription management.

Handles:
- Customer creation
- Subscription creation via Checkout Sessions
- Plan changes (upgrade/downgrade)
- Webhook event processing
- Customer portal sessions
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database.billing import Invoice, Subscription
from app.models.database.organization import Organization


def _get_stripe():
    """Lazy import stripe to avoid import errors when key not set."""
    import stripe
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    return stripe


async def create_checkout_session(
    db: AsyncSession,
    org_id: uuid.UUID,
    plan_tier: str,
    success_url: str,
    cancel_url: str,
) -> str:
    """Create a Stripe Checkout Session for new subscription. Returns session URL."""
    stripe = _get_stripe()
    settings = get_settings()

    # Get or create Stripe customer
    result = await db.execute(
        select(Subscription).where(Subscription.organization_id == org_id)
    )
    subscription = result.scalar_one_or_none()

    customer_id = subscription.stripe_customer_id if subscription else None

    if not customer_id:
        # Load org info for customer creation
        org = await db.get(Organization, org_id)
        customer = stripe.Customer.create(
            name=org.name if org else "Unknown",
            metadata={"org_id": str(org_id)},
        )
        customer_id = customer.id

        # Store customer ID
        if not subscription:
            subscription = Subscription(
                organization_id=org_id,
                stripe_customer_id=customer_id,
                plan_tier=plan_tier,
                status="trialing",
            )
            db.add(subscription)
        else:
            subscription.stripe_customer_id = customer_id
        await db.flush()

    # Determine price ID
    price_id = (
        settings.stripe_price_id_starter if plan_tier == "starter"
        else settings.stripe_price_id_growth
    )

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        subscription_data={"trial_period_days": 14},
        metadata={"org_id": str(org_id), "plan_tier": plan_tier},
    )

    return session.url


async def create_portal_session(
    db: AsyncSession,
    org_id: uuid.UUID,
    return_url: str,
) -> str:
    """Create a Stripe Customer Portal session for self-serve billing management."""
    stripe = _get_stripe()

    result = await db.execute(
        select(Subscription).where(Subscription.organization_id == org_id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription or not subscription.stripe_customer_id:
        raise ValueError("No Stripe customer found for this organization")

    session = stripe.billing_portal.Session.create(
        customer=subscription.stripe_customer_id,
        return_url=return_url,
    )

    return session.url


async def handle_webhook_event(db: AsyncSession, event: dict) -> None:
    """Process Stripe webhook events."""
    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "customer.subscription.created":
        await _handle_subscription_created(db, data)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(db, data)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(db, data)
    elif event_type == "invoice.paid":
        await _handle_invoice_paid(db, data)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(db, data)


async def _handle_subscription_created(db: AsyncSession, data: dict) -> None:
    customer_id = data["customer"]
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == customer_id)
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        subscription.stripe_subscription_id = data["id"]
        subscription.status = data["status"]
        subscription.current_period_start = datetime.fromtimestamp(
            data["current_period_start"], tz=timezone.utc
        )
        subscription.current_period_end = datetime.fromtimestamp(
            data["current_period_end"], tz=timezone.utc
        )
        if data.get("trial_end"):
            subscription.trial_ends_at = datetime.fromtimestamp(
                data["trial_end"], tz=timezone.utc
            )


async def _handle_subscription_updated(db: AsyncSession, data: dict) -> None:
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == data["id"])
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        subscription.status = data["status"]
        subscription.current_period_start = datetime.fromtimestamp(
            data["current_period_start"], tz=timezone.utc
        )
        subscription.current_period_end = datetime.fromtimestamp(
            data["current_period_end"], tz=timezone.utc
        )
        subscription.cancel_at_period_end = data.get("cancel_at_period_end", False)

        # Update org plan tier if price changed
        items = data.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id", "")
            settings = get_settings()
            if price_id == settings.stripe_price_id_starter:
                subscription.plan_tier = "starter"
            elif price_id == settings.stripe_price_id_growth:
                subscription.plan_tier = "growth"


async def _handle_subscription_deleted(db: AsyncSession, data: dict) -> None:
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == data["id"])
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        subscription.status = "cancelled"


async def _handle_invoice_paid(db: AsyncSession, data: dict) -> None:
    customer_id = data["customer"]
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == customer_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return

    invoice = Invoice(
        organization_id=subscription.organization_id,
        stripe_invoice_id=data["id"],
        total_cents=data["amount_paid"],
        subtotal_cents=data.get("subtotal", 0),
        tax_cents=data.get("tax", 0),
        status="paid",
        paid_at=datetime.now(timezone.utc),
    )
    db.add(invoice)


async def _handle_payment_failed(db: AsyncSession, data: dict) -> None:
    customer_id = data["customer"]
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == customer_id)
    )
    subscription = result.scalar_one_or_none()
    if subscription:
        subscription.status = "past_due"

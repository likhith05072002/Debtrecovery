"""Billing and subscription management endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.permissions import enforce_role
from app.dependencies import get_current_user, get_db, get_redis
from app.models.database.billing import Invoice, PlanLimit, Subscription
from app.models.database.user import User
from app.services.billing.stripe_service import (
    create_checkout_session,
    create_portal_session,
    handle_webhook_event,
)
from app.services.billing.usage_meter import get_current_usage, get_monthly_usage

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class SubscriptionResponse(BaseModel):
    plan_tier: str
    status: str
    trial_ends_at: str | None
    current_period_end: str | None
    cancel_at_period_end: bool


class UsageResponse(BaseModel):
    ai_minutes_today: float
    ai_calls_today: int
    api_calls_today: int
    ai_minutes_month: float
    ai_calls_month: int
    successful_collections_month: float


class PlanLimitResponse(BaseModel):
    tier: str
    monthly_ai_minutes: int | None
    monthly_calls: int | None
    max_borrowers: int | None
    max_campaigns: int | None
    max_users: int | None
    base_price_cents: int
    per_minute_rate_cents: int
    features: dict | None


class CheckoutRequest(BaseModel):
    plan_tier: str
    success_url: str
    cancel_url: str


class PortalRequest(BaseModel):
    return_url: str


class InvoiceResponse(BaseModel):
    id: str
    stripe_invoice_id: str | None
    period_start: str | None
    period_end: str | None
    total_cents: int
    status: str
    paid_at: str | None
    created_at: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/subscription", response_model=SubscriptionResponse)
async def get_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current subscription details."""
    result = await db.execute(
        select(Subscription).where(Subscription.organization_id == current_user.organization_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return SubscriptionResponse(
            plan_tier="starter",
            status="trialing",
            trial_ends_at=None,
            current_period_end=None,
            cancel_at_period_end=False,
        )

    return SubscriptionResponse(
        plan_tier=sub.plan_tier,
        status=sub.status,
        trial_ends_at=sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
        current_period_end=sub.current_period_end.isoformat() if sub.current_period_end else None,
        cancel_at_period_end=sub.cancel_at_period_end,
    )


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Get current usage (real-time from Redis + monthly from PostgreSQL)."""
    org_id = current_user.organization_id
    today_usage = await get_current_usage(redis, org_id)
    monthly_usage = await get_monthly_usage(db, org_id)

    return UsageResponse(
        ai_minutes_today=today_usage["ai_minutes_today"],
        ai_calls_today=today_usage["ai_calls_today"],
        api_calls_today=today_usage["api_calls_today"],
        ai_minutes_month=monthly_usage["ai_minutes_month"] + today_usage["ai_minutes_today"],
        ai_calls_month=monthly_usage["ai_calls_month"] + today_usage["ai_calls_today"],
        successful_collections_month=monthly_usage["successful_collections_month"],
    )


@router.get("/plans", response_model=list[PlanLimitResponse])
async def list_plans(db: AsyncSession = Depends(get_db)):
    """List all available plan tiers and their limits (public endpoint)."""
    result = await db.execute(select(PlanLimit).order_by(PlanLimit.base_price_cents))
    plans = result.scalars().all()
    return [
        PlanLimitResponse(
            tier=p.tier,
            monthly_ai_minutes=p.monthly_ai_minutes,
            monthly_calls=p.monthly_calls,
            max_borrowers=p.max_borrowers,
            max_campaigns=p.max_campaigns,
            max_users=p.max_users,
            base_price_cents=p.base_price_cents,
            per_minute_rate_cents=p.per_minute_rate_cents,
            features=p.features,
        )
        for p in plans
    ]


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for subscribing. Returns redirect URL."""
    enforce_role(current_user.role, "admin")

    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Stripe not configured")

    url = await create_checkout_session(
        db=db,
        org_id=current_user.organization_id,
        plan_tier=body.plan_tier,
        success_url=body.success_url,
        cancel_url=body.cancel_url,
    )
    return {"checkout_url": url}


@router.post("/portal")
async def create_billing_portal(
    body: PortalRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Customer Portal session for self-serve billing management."""
    enforce_role(current_user.role, "admin")

    try:
        url = await create_portal_session(db, current_user.organization_id, body.return_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"portal_url": url}


@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all invoices for the organization."""
    result = await db.execute(
        select(Invoice)
        .where(Invoice.organization_id == current_user.organization_id)
        .order_by(Invoice.created_at.desc())
        .limit(50)
    )
    invoices = result.scalars().all()
    return [
        InvoiceResponse(
            id=str(inv.id),
            stripe_invoice_id=inv.stripe_invoice_id,
            period_start=inv.period_start.isoformat() if inv.period_start else None,
            period_end=inv.period_end.isoformat() if inv.period_end else None,
            total_cents=inv.total_cents,
            status=inv.status,
            paid_at=inv.paid_at.isoformat() if inv.paid_at else None,
            created_at=inv.created_at.isoformat(),
        )
        for inv in invoices
    ]


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events. Verifies signature before processing."""
    import stripe

    settings = get_settings()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    await handle_webhook_event(db, event)
    return {"received": True}

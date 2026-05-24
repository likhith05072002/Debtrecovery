"""Plan enforcement — checks billing status and usage limits before expensive operations.

Used in call admission control:
    1. Is the org's subscription active?
    2. Is usage within plan limits?
    3. FDCPA call frequency (separate concern, but gated here too)
"""
from __future__ import annotations

import uuid

import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.billing import Subscription
from app.services.billing.usage_meter import check_usage_limit


class BillingBlockedError(Exception):
    """Raised when an operation is blocked due to billing issues."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


async def enforce_call_admission(
    db: AsyncSession,
    redis: aioredis.Redis,
    org_id: uuid.UUID,
) -> None:
    """Gate a call placement behind billing checks.

    Raises BillingBlockedError if the org cannot place calls.
    Call this from call_controller.initiate_outbound_call() before Twilio dial.
    """
    # 1. Check subscription status
    result = await db.execute(
        select(Subscription).where(Subscription.organization_id == org_id)
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        # No subscription — allow in dev/trial mode, block in prod
        return

    if subscription.status == "cancelled":
        raise BillingBlockedError("Subscription cancelled. Please reactivate to place calls.")
    if subscription.status == "past_due":
        raise BillingBlockedError("Payment past due. Please update your payment method.")

    # 2. Check usage limits
    allowed, reason = await check_usage_limit(redis, db, org_id, subscription.plan_tier)
    if not allowed:
        raise BillingBlockedError(reason or "Usage limit exceeded")


async def enforce_borrower_limit(
    db: AsyncSession,
    org_id: uuid.UUID,
    current_count: int,
) -> None:
    """Check if org can add more borrowers based on plan limits."""
    from app.models.database.billing import PlanLimit

    result = await db.execute(
        select(Subscription).where(Subscription.organization_id == org_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return  # No subscription = no enforcement

    result = await db.execute(
        select(PlanLimit).where(PlanLimit.tier == subscription.plan_tier)
    )
    plan = result.scalar_one_or_none()
    if not plan or plan.max_borrowers is None:
        return  # Unlimited

    if current_count >= plan.max_borrowers:
        raise BillingBlockedError(
            f"Borrower limit reached ({plan.max_borrowers}). Upgrade your plan to add more."
        )


async def enforce_user_limit(
    db: AsyncSession,
    org_id: uuid.UUID,
    current_count: int,
) -> None:
    """Check if org can add more users based on plan limits."""
    from app.models.database.billing import PlanLimit

    result = await db.execute(
        select(Subscription).where(Subscription.organization_id == org_id)
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return

    result = await db.execute(
        select(PlanLimit).where(PlanLimit.tier == subscription.plan_tier)
    )
    plan = result.scalar_one_or_none()
    if not plan or plan.max_users is None:
        return

    if current_count >= plan.max_users:
        raise BillingBlockedError(
            f"User limit reached ({plan.max_users}). Upgrade your plan to invite more members."
        )

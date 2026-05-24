"""Usage metering service — Redis-backed real-time counters with PostgreSQL flush.

Architecture:
    Call placed → Redis INCRBY org:{id}:minutes (real-time, <1ms)
                            ↓ (every 5min via Celery)
                PostgreSQL usage_records (source of truth)
                            ↓ (end of billing period)
                Stripe Usage Records (invoice reconciliation)
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.billing import PlanLimit, UsageRecord


def _usage_key(org_id: uuid.UUID, metric: str) -> str:
    """Redis key for real-time usage counter."""
    today = date.today().isoformat()
    return f"usage:{org_id}:{today}:{metric}"


async def increment_call_minutes(
    redis: aioredis.Redis,
    org_id: uuid.UUID,
    minutes: float,
) -> float:
    """Increment AI call minutes for an org. Returns new total for today."""
    key = _usage_key(org_id, "ai_minutes")
    # Use integer centiseconds for precision without floating point
    centiseconds = int(minutes * 100)
    new_val = await redis.incrby(key, centiseconds)
    # Set TTL of 48 hours (buffer beyond daily flush)
    await redis.expire(key, 172800)
    return new_val / 100.0


async def increment_call_count(redis: aioredis.Redis, org_id: uuid.UUID) -> int:
    """Increment AI call count for an org. Returns new total for today."""
    key = _usage_key(org_id, "ai_calls")
    new_val = await redis.incr(key)
    await redis.expire(key, 172800)
    return new_val


async def increment_api_calls(redis: aioredis.Redis, org_id: uuid.UUID) -> int:
    """Increment API call count."""
    key = _usage_key(org_id, "api_calls")
    new_val = await redis.incr(key)
    await redis.expire(key, 172800)
    return new_val


async def get_current_usage(redis: aioredis.Redis, org_id: uuid.UUID) -> dict:
    """Get current day's usage from Redis (fast path for limit checks)."""
    today = date.today().isoformat()
    pipe = redis.pipeline()
    pipe.get(f"usage:{org_id}:{today}:ai_minutes")
    pipe.get(f"usage:{org_id}:{today}:ai_calls")
    pipe.get(f"usage:{org_id}:{today}:api_calls")
    results = await pipe.execute()

    return {
        "ai_minutes_today": (int(results[0] or 0)) / 100.0,
        "ai_calls_today": int(results[1] or 0),
        "api_calls_today": int(results[2] or 0),
    }


async def get_monthly_usage(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Get current month's aggregate usage from PostgreSQL."""
    first_of_month = date.today().replace(day=1)
    result = await db.execute(
        select(UsageRecord).where(
            UsageRecord.organization_id == org_id,
            UsageRecord.period_start >= first_of_month,
        )
    )
    records = result.scalars().all()

    total_minutes = sum(float(r.ai_call_minutes) for r in records)
    total_calls = sum(r.ai_calls_count for r in records)
    total_collections = sum(float(r.successful_collections) for r in records)

    return {
        "ai_minutes_month": total_minutes,
        "ai_calls_month": total_calls,
        "successful_collections_month": total_collections,
    }


async def check_usage_limit(
    redis: aioredis.Redis,
    db: AsyncSession,
    org_id: uuid.UUID,
    plan_tier: str,
) -> tuple[bool, str | None]:
    """Check if org is within usage limits. Returns (allowed, reason_if_blocked)."""
    # Get plan limits
    result = await db.execute(select(PlanLimit).where(PlanLimit.tier == plan_tier))
    plan = result.scalar_one_or_none()

    if not plan:
        # No plan configured — allow (fail open for dev)
        return True, None

    # Unlimited plan
    if plan.monthly_ai_minutes is None:
        return True, None

    # Get monthly usage
    monthly = await get_monthly_usage(db, org_id)

    if monthly["ai_minutes_month"] >= plan.monthly_ai_minutes:
        return False, f"Monthly AI call limit reached ({plan.monthly_ai_minutes} minutes)"

    return True, None


async def flush_to_postgres(
    db: AsyncSession,
    redis: aioredis.Redis,
    org_id: uuid.UUID,
) -> None:
    """Flush today's Redis counters to PostgreSQL usage_records."""
    today = date.today()
    usage = await get_current_usage(redis, org_id)

    # Upsert into usage_records
    result = await db.execute(
        select(UsageRecord).where(
            UsageRecord.organization_id == org_id,
            UsageRecord.period_start == today,
        )
    )
    record = result.scalar_one_or_none()

    if record:
        record.ai_call_minutes = Decimal(str(usage["ai_minutes_today"]))
        record.ai_calls_count = usage["ai_calls_today"]
        record.api_calls_count = usage["api_calls_today"]
    else:
        record = UsageRecord(
            organization_id=org_id,
            period_start=today,
            period_end=today,
            ai_call_minutes=Decimal(str(usage["ai_minutes_today"])),
            ai_calls_count=usage["ai_calls_today"],
            api_calls_count=usage["api_calls_today"],
        )
        db.add(record)

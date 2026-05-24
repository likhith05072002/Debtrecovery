"""
Opt-out processing — handles cease-and-desist requests immediately.

On opt-out:
1. Set borrower.opted_out = True, borrower.do_not_call = True
2. Add phone_hash to Redis DNC set (permanent)
3. Cancel all pending call_schedule entries for this borrower
4. Log ComplianceEvent (opt_out_received)
5. Respond immediately — no retry window
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.borrower import Borrower
from app.models.database.campaign import CallSchedule
from app.models.database.compliance import ComplianceEvent
from app.services.memory.redis_session import set_dnc
from app.utils.crypto import decrypt_pii, hash_pii

logger = logging.getLogger(__name__)


async def process_opt_out(
    borrower: Borrower,
    db: AsyncSession,
    trigger: str,
    channel: str = "all",
) -> None:
    """
    Immediately process a borrower opt-out request.
    This must run synchronously during the live call — before the call ends.
    """
    now = datetime.now(timezone.utc)

    # 1. Update borrower record
    borrower.opted_out = True
    borrower.opted_out_at = now
    if channel in ("voice", "all"):
        borrower.do_not_call = True

    # 2. Add to Redis DNC (instant enforcement for future calls)
    phone_e164 = decrypt_pii(borrower.phone_e164)
    phone_hash = hash_pii(phone_e164)
    await set_dnc(phone_hash)

    # 3. Cancel all pending scheduled calls for this borrower
    await db.execute(
        update(CallSchedule)
        .where(CallSchedule.borrower_id == borrower.id, CallSchedule.status == "pending")
        .values(status="cancelled")
    )

    # 4. Log compliance event
    event = ComplianceEvent(
        borrower_id=borrower.id,
        event_type="opt_out_received",
        severity="violation",
        description=f"Opt-out received via {channel}. Trigger: '{trigger}'",
        auto_actioned=True,
    )
    db.add(event)

    logger.info("Opt-out processed for borrower %s (trigger: %s)", borrower.id, trigger)


async def process_dispute(
    borrower: Borrower,
    db: AsyncSession,
    call_id: str,
    dispute_reason: str,
    amount_disputed: float | None = None,
) -> None:
    """
    Log a debt dispute and flag the account.
    Collection activity must stop immediately per FDCPA §809.
    """
    description = f"Debt disputed: {dispute_reason}"
    if amount_disputed:
        description += f" (amount: INR {amount_disputed:,.2f})"

    event = ComplianceEvent(
        borrower_id=borrower.id,
        call_id=call_id,
        event_type="dispute_received",
        severity="warning",
        description=description,
        auto_actioned=True,
    )
    db.add(event)
    logger.info("Dispute logged for borrower %s: %s", borrower.id, dispute_reason)

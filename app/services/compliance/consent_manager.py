"""
TCPA consent management — records and verifies consent for automated calls.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database.borrower import Borrower
from app.models.database.compliance import ComplianceEvent

logger = logging.getLogger(__name__)


async def record_consent(borrower: Borrower, db: AsyncSession) -> None:
    """Mark that TCPA consent has been obtained for automated outbound calls."""
    now = datetime.now(timezone.utc)
    borrower.consent_recorded = True
    borrower.consent_recorded_at = now

    event = ComplianceEvent(
        borrower_id=borrower.id,
        event_type="consent_obtained",
        severity="info",
        description="TCPA consent recorded for automated outbound calls",
        auto_actioned=True,
    )
    db.add(event)
    logger.info("Consent recorded for borrower %s", borrower.id)


async def record_recording_consent(borrower_id, call_id, db: AsyncSession) -> None:
    """Log that the borrower was informed the call may be recorded."""
    event = ComplianceEvent(
        borrower_id=borrower_id,
        call_id=call_id,
        event_type="recording_consent_obtained",
        severity="info",
        description="Borrower notified that call may be recorded",
        auto_actioned=True,
    )
    db.add(event)

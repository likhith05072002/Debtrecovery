"""
Outbound call lifecycle manager.
Replaces the original make_call.py stub with a full database-driven implementation.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database.call import Call
from app.models.database.borrower import Borrower
from app.services.telephony.twilio_client import get_twilio_client, build_media_stream_twiml
from app.services.compliance.fdcpa_guard import pre_call_compliance_check
from app.services.memory.redis_session import set_call_setup_metadata
from app.utils.crypto import decrypt_pii

logger = logging.getLogger(__name__)


async def initiate_outbound_call(
    borrower: Borrower,
    db: AsyncSession,
    campaign_id: uuid.UUID | None = None,
    strategy_hint: str | None = None,
    follow_up_enabled: bool = False,
    follow_up_source_call_id: uuid.UUID | None = None,
) -> Call:
    """
    Perform pre-call compliance checks, create a Call record, then trigger
    Twilio to dial the borrower. Returns the Call ORM object (status=initiated).
    """
    settings = get_settings()

    # Layer 1: Compliance gate — abort if any check fails
    await pre_call_compliance_check(borrower, db)

    # Decrypt phone number for dialing
    phone_number = decrypt_pii(borrower.phone_e164)

    # Create call record before dialing (to capture SID on success)
    call = Call(
        borrower_id=borrower.id,
        campaign_id=campaign_id,
        from_number=settings.twilio_from_number,
        to_number=phone_number,
        status="initiated",
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    await db.flush()   # Get the UUID without committing

    # Twilio webhook URL returns TwiML that opens Media Streams
    webhook_url = f"{settings.twilio_webhook_base_url}/api/v1/telephony/voice"
    status_callback = f"{settings.twilio_webhook_base_url}/api/v1/telephony/status_callback"

    # In dev mode with localhost webhook, fall back to demo TwiML so the phone still rings
    is_localhost = settings.twilio_webhook_base_url.startswith("http://localhost")
    effective_url = "http://demo.twilio.com/docs/voice.xml" if (not settings.is_production and is_localhost) else webhook_url
    effective_status_cb = status_callback if not is_localhost else None

    try:
        client = get_twilio_client()
        twilio_call = client.calls.create(
            to=phone_number,
            from_=settings.twilio_from_number,
            url=effective_url,
            status_callback=effective_status_cb,
            status_callback_event=["initiated", "ringing", "answered", "completed"],
            record=True,
            recording_status_callback=(
                f"{settings.twilio_webhook_base_url}/api/v1/telephony/recording_callback"
                if not is_localhost else None
            ),
        )
        call.twilio_call_sid = twilio_call.sid
        call.status = "ringing"
        await set_call_setup_metadata(
            twilio_call.sid,
            {
                "strategy_hint": strategy_hint,
                "follow_up_enabled": follow_up_enabled,
                "follow_up_source_call_id": str(follow_up_source_call_id) if follow_up_source_call_id else None,
            },
        )
        logger.info("Outbound call placed: sid=%s borrower=%s", twilio_call.sid, borrower.id)
    except Exception as exc:
        call.status = "failed"
        call.ended_at = datetime.now(timezone.utc)
        logger.error("Failed to place call for borrower %s: %s", borrower.id, exc)
        raise

    return call

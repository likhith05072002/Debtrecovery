"""
Outbound call lifecycle manager.

Supports two backends:
- LiveKit SIP (default) — audio via LiveKit Cloud, agent via livekit_worker.py
- Twilio direct (legacy) — audio via Twilio Media Streams WebSocket

The backend is selected based on whether LIVEKIT_URL is configured.
All FDCPA compliance checks, DB record creation, and Redis metadata
are identical regardless of backend.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.database.call import Call
from app.models.database.borrower import Borrower
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
    an outbound call via LiveKit SIP (or Twilio direct as fallback).

    Returns the Call ORM object (status=initiated).
    """
    settings = get_settings()

    # Layer 1: Compliance gate — abort if any check fails
    await pre_call_compliance_check(borrower, db)

    # Decrypt phone number for dialing
    phone_number = decrypt_pii(borrower.phone_e164)

    # Create call record before dialing
    call = Call(
        organization_id=borrower.organization_id,
        borrower_id=borrower.id,
        campaign_id=campaign_id,
        from_number=settings.twilio_from_number,
        to_number=phone_number,
        status="initiated",
        started_at=datetime.now(timezone.utc),
    )
    db.add(call)
    await db.flush()  # Get the UUID

    # Build follow-up context if enabled
    follow_up_context = ""
    if follow_up_enabled and follow_up_source_call_id:
        from app.services.follow_up.follow_up_brief import build_follow_up_brief
        brief = await build_follow_up_brief(db, str(borrower.id), str(follow_up_source_call_id))
        if brief:
            follow_up_context = brief.summary or ""

    # ── Route to backend ─────────────────────────────────────────────────────

    if settings.livekit_url:
        # LiveKit SIP backend (preferred)
        await _place_via_livekit(call, phone_number, borrower, db, strategy_hint, follow_up_context)
    else:
        # Legacy Twilio direct backend
        await _place_via_twilio(call, phone_number, borrower, db, strategy_hint, follow_up_enabled, follow_up_source_call_id)

    return call


async def _place_via_livekit(
    call: Call,
    phone_number: str,
    borrower: Borrower,
    db: AsyncSession,
    strategy_hint: str | None,
    follow_up_context: str,
) -> None:
    """Place call via LiveKit SIP trunk."""
    from app.services.telephony.livekit_sip import place_outbound_call

    try:
        room_name, sip_participant_id = await place_outbound_call(
            phone_number=phone_number,
            call_sid=str(call.id),
            borrower_id=borrower.id,
            organization_id=borrower.organization_id,
            campaign_id=call.campaign_id,
            strategy_hint=strategy_hint,
            follow_up_context=follow_up_context,
        )
        call.livekit_room_name = room_name
        call.status = "ringing"
        logger.info("LiveKit SIP call placed: room=%s borrower=%s", room_name, borrower.id)

    except Exception as exc:
        call.status = "failed"
        call.ended_at = datetime.now(timezone.utc)
        logger.error("LiveKit SIP call failed for borrower %s: %s", borrower.id, exc)
        raise


async def _place_via_twilio(
    call: Call,
    phone_number: str,
    borrower: Borrower,
    db: AsyncSession,
    strategy_hint: str | None,
    follow_up_enabled: bool,
    follow_up_source_call_id: uuid.UUID | None,
) -> None:
    """Legacy: place call via Twilio REST API + Media Streams WebSocket."""
    from app.services.telephony.twilio_client import get_twilio_client

    settings = get_settings()
    webhook_url = f"{settings.twilio_webhook_base_url}/api/v1/telephony/voice"
    status_callback = f"{settings.twilio_webhook_base_url}/api/v1/telephony/status_callback"

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
        logger.info("Twilio call placed: sid=%s borrower=%s", twilio_call.sid, borrower.id)

    except Exception as exc:
        call.status = "failed"
        call.ended_at = datetime.now(timezone.utc)
        logger.error("Twilio call failed for borrower %s: %s", borrower.id, exc)
        raise

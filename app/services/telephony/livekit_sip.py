"""
LiveKit SIP outbound calling service.

Replaces direct Twilio API calls with LiveKit's SIP integration.
Twilio still handles the PSTN leg (via SIP trunk), but LiveKit manages
the audio pipeline, agent dispatch, and WebRTC transport.

Flow:
    1. FastAPI receives POST /api/v1/calls/initiate
    2. call_controller runs FDCPA checks, creates Call DB record
    3. This module calls LiveKit's CreateSIPParticipant API
    4. LiveKit sends SIP INVITE to Twilio SIP trunk
    5. Twilio dials the borrower's phone
    6. Borrower answers → LiveKit bridges SIP ↔ WebRTC
    7. LiveKit dispatches livekit_worker.py which runs DebtCollectorAgent
"""
from __future__ import annotations

import json
import logging
import uuid

from livekit.api import LiveKitAPI, CreateSIPParticipantRequest

from app.config import get_settings

logger = logging.getLogger(__name__)


async def place_outbound_call(
    phone_number: str,
    call_sid: str,
    borrower_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
    strategy_hint: str | None = None,
    follow_up_context: str = "",
) -> tuple[str, str]:
    """Place an outbound call via LiveKit SIP.

    Args:
        phone_number: E.164 phone number to dial
        call_sid: Internal call ID (UUID)
        borrower_id: Borrower database ID
        organization_id: Tenant org ID
        campaign_id: Optional campaign ID
        strategy_hint: Optional strategy override
        follow_up_context: Context from previous calls

    Returns:
        (room_name, sip_participant_id) tuple
    """
    settings = get_settings()

    # Generate unique room name for this call
    room_name = f"call-{call_sid}"

    # Metadata passed to the agent worker via room metadata
    room_metadata = json.dumps({
        "call_sid": str(call_sid),
        "borrower_id": str(borrower_id),
        "organization_id": str(organization_id) if organization_id else None,
        "campaign_id": str(campaign_id) if campaign_id else None,
        "strategy_hint": strategy_hint,
        "follow_up_context": follow_up_context,
    })

    # Create LiveKit API client
    api = LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )

    try:
        # Create a SIP participant — LiveKit sends SIP INVITE via configured trunk
        participant = await api.sip.create_sip_participant(
            CreateSIPParticipantRequest(
                sip_trunk_id=settings.sip_outbound_trunk_id,
                sip_call_to=phone_number,
                room_name=room_name,
                participant_identity=f"borrower-{borrower_id}",
                participant_name="Borrower",
                participant_metadata=json.dumps({"borrower_id": str(borrower_id)}),
                # Pass call metadata via room metadata so agent worker can read it
                room_metadata=room_metadata,
                # Enable Krisp noise cancellation
                krisp_enabled=True,
            )
        )

        sip_participant_id = participant.participant_id if hasattr(participant, "participant_id") else str(participant)
        logger.info(
            "LiveKit SIP call placed: room=%s phone=%s trunk=%s",
            room_name, phone_number[-4:], settings.sip_outbound_trunk_id,
        )

        return room_name, sip_participant_id

    except Exception as exc:
        logger.error("LiveKit SIP call failed: %s", exc)
        raise
    finally:
        await api.aclose()

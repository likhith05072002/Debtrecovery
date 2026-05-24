"""
Twilio webhook endpoints.
These receive callbacks from Twilio when calls connect, status changes, or recordings complete.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.database.call import Call
from app.models.database.human_call import HumanCall
from twilio.twiml.voice_response import VoiceResponse, Connect, Stream

from app.config import get_settings
from app.services.telephony.twilio_client import build_media_stream_twiml, validate_twilio_request
from fastapi import Depends

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/voice", response_class=PlainTextResponse)
async def voice_webhook(
    request: Request,
    CallSid: str = Form(...),
    From: str = Form(default=""),
    To: str = Form(default=""),
    CallStatus: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """
    Twilio calls this when a call connects.
    We respond with TwiML that opens a Media Streams WebSocket.
    """
    # Validate Twilio signature in production
    # signature = request.headers.get("X-Twilio-Signature", "")
    # form_data = dict(await request.form())
    # if not validate_twilio_request(str(request.url), form_data, signature):
    #     raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    logger.info("Twilio voice webhook: CallSid=%s Status=%s", CallSid, CallStatus)

    # Update call record with Twilio SID
    result = await db.execute(select(Call).where(Call.twilio_call_sid == CallSid))
    call = result.scalar_one_or_none()
    if call:
        call.status = "in-progress"
        call.answered_at = datetime.now(timezone.utc)

    twiml = build_media_stream_twiml(CallSid)
    return Response(content=twiml, media_type="text/xml")


@router.post("/status_callback")
async def status_callback(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: str = Form(default="0"),
    db: AsyncSession = Depends(get_db),
):
    """Twilio call status updates (ringing, answered, completed, failed, etc.)."""
    logger.info("Twilio status callback: CallSid=%s Status=%s", CallSid, CallStatus)

    result = await db.execute(select(Call).where(Call.twilio_call_sid == CallSid))
    call = result.scalar_one_or_none()
    if not call:
        return {"status": "not_found"}

    call.status = CallStatus.lower().replace("-", "_")

    if CallStatus in ("completed", "failed", "canceled", "busy", "no-answer"):
        call.ended_at = datetime.now(timezone.utc)
        try:
            call.duration_seconds = int(CallDuration)
        except ValueError:
            pass

        if CallStatus == "no-answer":
            call.outcome = "no_answer"
        elif CallStatus == "busy":
            call.outcome = "busy"

    return {"status": "ok"}


@router.post("/recording_callback")
async def recording_callback(
    CallSid: str = Form(...),
    RecordingUrl: str = Form(default=""),
    RecordingDuration: str = Form(default="0"),
    db: AsyncSession = Depends(get_db),
):
    """Twilio delivers recording URL after AI call ends (human calls use Media Streams, not recordings)."""
    result = await db.execute(select(Call).where(Call.twilio_call_sid == CallSid))
    call = result.scalar_one_or_none()
    if call and RecordingUrl:
        call.recording_url = RecordingUrl + ".mp3"
        logger.info("Recording stored for AI call %s: %s", CallSid, RecordingUrl)
    return {"status": "ok"}


@router.post("/voice_human/{human_call_id}", response_class=PlainTextResponse)
async def voice_webhook_human(
    request: Request,
    human_call_id: uuid.UUID,
    CallSid: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    TwiML for human-agent calls.
    Opens a Twilio Media Streams WebSocket so Deepgram can transcribe in real-time.
    The WebSocket handler runs GPT-4o analysis when the call ends.
    """
    import uuid as _uuid
    human_call = await db.get(HumanCall, human_call_id)
    if human_call:
        human_call.twilio_call_sid = CallSid
        human_call.status = "in_progress"

    settings = get_settings()
    ws_url = f"{settings.twilio_webhook_base_url.replace('http', 'ws', 1)}/ws/human/{CallSid}"

    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=ws_url)
    stream.parameter(name="humanCallId", value=str(human_call_id))
    connect.append(stream)
    response.append(connect)

    return Response(content=str(response), media_type="text/xml")


@router.post("/voice_client", response_class=PlainTextResponse)
async def voice_client_webhook(
    request: Request,
    CallSid: str = Form(...),
    humanCallId: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    TwiML App Voice URL — Twilio hits this when the browser SDK calls device.connect().
    Looks up the HumanCall record, decrypts the borrower's phone, then returns TwiML that:
      1. Starts a Media Streams WebSocket for real-time Deepgram transcription
      2. Dials the borrower's phone number (bridging agent browser ↔ borrower phone)
    """
    from twilio.twiml.voice_response import Dial, Start

    settings = get_settings()

    try:
        hc_id = uuid.UUID(humanCallId)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid humanCallId")

    human_call = await db.get(HumanCall, hc_id)
    if not human_call:
        raise HTTPException(status_code=404, detail="HumanCall not found")

    if not human_call.contact_phone:
        raise HTTPException(status_code=400, detail="No phone number on this call record")

    phone_number = human_call.contact_phone

    # Update call record with Twilio SID
    human_call.twilio_call_sid = CallSid
    human_call.status = "in_progress"
    await db.commit()

    ws_url = f"{settings.websocket_url}/ws/human/{CallSid}"

    response = VoiceResponse()

    # Fork audio to our WebSocket for real-time transcription (non-blocking)
    start = Start()
    stream = Stream(url=ws_url)
    stream.parameter(name="humanCallId", value=humanCallId)
    start.append(stream)
    response.append(start)

    # Dial the borrower (bridges agent browser ↔ borrower phone)
    dial = Dial(caller_id=settings.twilio_from_number)
    dial.number(phone_number)
    response.append(dial)

    logger.info("voice_client TwiML: CallSid=%s humanCallId=%s phone=%s", CallSid, humanCallId, phone_number[-4:])
    return Response(content=str(response), media_type="text/xml")


@router.post("/status_callback_human")
async def status_callback_human(
    CallSid: str = Form(...),
    CallStatus: str = Form(...),
    CallDuration: str = Form(default="0"),
    db: AsyncSession = Depends(get_db),
):
    """Twilio call status updates for human calls."""
    logger.info("Human call status: CallSid=%s Status=%s", CallSid, CallStatus)

    result = await db.execute(select(HumanCall).where(HumanCall.twilio_call_sid == CallSid))
    human_call = result.scalar_one_or_none()
    if not human_call:
        return {"status": "not_found"}

    human_call.status = CallStatus.lower().replace("-", "_")
    if CallStatus in ("completed", "failed", "canceled", "busy", "no-answer"):
        human_call.ended_at = datetime.now(timezone.utc)
        try:
            human_call.duration_seconds = int(CallDuration)
        except ValueError:
            pass

    return {"status": "ok"}

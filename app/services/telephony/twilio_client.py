"""Twilio REST client — outbound call initiation and TwiML generation."""
from __future__ import annotations

import logging
from functools import lru_cache

from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, Stream, VoiceResponse

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_twilio_client() -> Client:
    settings = get_settings()
    return Client(settings.twilio_account_sid, settings.twilio_auth_token)


@lru_cache(maxsize=1)
def get_request_validator() -> RequestValidator:
    settings = get_settings()
    return RequestValidator(settings.twilio_auth_token)


def build_media_stream_twiml(call_sid: str) -> str:
    """
    Return TwiML that opens a Twilio Media Stream WebSocket connection.
    Twilio will stream bidirectional audio to our /ws/media/{call_sid} endpoint.
    """
    settings = get_settings()
    ws_url = f"{settings.websocket_url}/ws/media/{call_sid}"

    response = VoiceResponse()
    connect = Connect()
    stream = Stream(url=ws_url)
    stream.parameter(name="callSid", value=call_sid)
    connect.append(stream)
    response.append(connect)
    return str(response)


def validate_twilio_request(url: str, params: dict, signature: str) -> bool:
    """Verify Twilio webhook authenticity using X-Twilio-Signature."""
    validator = get_request_validator()
    return validator.validate(url, params, signature)

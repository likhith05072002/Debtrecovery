"""
Deepgram streaming STT client.
Maintains one persistent WebSocket per call for lowest latency.
Calls back on_transcript(transcript, confidence, is_final) when speech is detected.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed

from app.config import get_settings

logger = logging.getLogger(__name__)

TranscriptCallback = Callable[[str, float, bool], Awaitable[None]]

# Map preferred_language codes → Deepgram language parameter
LANGUAGE_TO_DEEPGRAM = {
    "en": "en-IN",
    "hi": "hi",
    "kn": "multi",   # Nova-2 doesn't support kn natively
    "te": "multi",   # Nova-2 doesn't support te natively
}


class DeepgramStreamingClient:
    """
    Manages a single Deepgram Nova-2 streaming WebSocket connection per call.

    Usage:
        client = DeepgramStreamingClient(on_transcript=handler)
        await client.connect()
        await client.send_audio(pcm_bytes)
        await client.close()
    """

    WS_URL = "wss://api.deepgram.com/v1/listen"

    def __init__(self, on_transcript: TranscriptCallback, language: str = "en") -> None:
        self._on_transcript = on_transcript
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._receiver_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        settings = get_settings()
        self._api_key = settings.deepgram_api_key
        self._model = settings.deepgram_model
        self._endpointing = settings.deepgram_endpointing_ms
        self._language = LANGUAGE_TO_DEEPGRAM.get(language, "en-IN")

    async def connect(self) -> None:
        """Open the Deepgram WebSocket and start the receiver coroutine."""
        params = (
            f"?model={self._model}"
            f"&encoding=linear16"
            f"&sample_rate=8000"
            f"&channels=1"
            f"&interim_results=true"
            f"&endpointing={self._endpointing}"
            f"&utterance_end_ms=1000"
            f"&smart_format=true"
            f"&punctuate=true"
            f"&language={self._language}"
        )
        headers = {"Authorization": f"Token {self._api_key}"}
        self._ws = await websockets.connect(
            self.WS_URL + params,
            extra_headers=headers,
            ping_interval=None,   # Deepgram doesn't respond to WS pings; use app-level keepalive instead
            ping_timeout=None,
        )
        self._receiver_task = asyncio.create_task(self._receive_loop())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.debug("Deepgram WS connected")

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Send a PCM audio chunk to Deepgram for transcription."""
        if self._ws and not self._ws.closed:
            await self._ws.send(pcm_bytes)

    async def flush(self) -> None:
        """Send utterance_end to force Deepgram to finalize current utterance."""
        if self._ws and not self._ws.closed:
            await self._ws.send(json.dumps({"type": "UtteranceEnd"}))

    async def close(self) -> None:
        """Gracefully close the Deepgram WebSocket."""
        if self._ws and not self._ws.closed:
            await self._ws.send(json.dumps({"type": "CloseStream"}))
            await self._ws.close()
        if self._receiver_task:
            self._receiver_task.cancel()
        if self._keepalive_task:
            self._keepalive_task.cancel()
        logger.debug("Deepgram WS closed")

    async def _keepalive_loop(self) -> None:
        """Send periodic KeepAlive to prevent Deepgram session timeout (~100s)."""
        try:
            while True:
                await asyncio.sleep(8)
                if self._ws and not self._ws.closed:
                    await self._ws.send(json.dumps({"type": "KeepAlive"}))
                    logger.debug("Deepgram KeepAlive sent")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Deepgram keepalive error: %s", exc)

    async def _receive_loop(self) -> None:
        """Parse incoming Deepgram messages and invoke transcript callback."""
        try:
            async for message in self._ws:
                await self._handle_message(message)
        except ConnectionClosed:
            logger.debug("Deepgram WS connection closed")
        except Exception as exc:
            logger.error("Deepgram receiver error: %s", exc)

    async def _handle_message(self, raw: str | bytes) -> None:
        if isinstance(raw, bytes):
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return

        msg_type = data.get("type")
        if msg_type == "Results":
            channel = data.get("channel", {})
            alternatives = channel.get("alternatives", [])
            if not alternatives:
                return
            transcript = alternatives[0].get("transcript", "").strip()
            confidence = alternatives[0].get("confidence", 0.0)
            is_final = data.get("is_final", False)
            speech_final = data.get("speech_final", False)

            if transcript and (is_final or speech_final):
                await self._on_transcript(transcript, confidence, True)
            elif transcript and not is_final:
                await self._on_transcript(transcript, confidence, False)

        elif msg_type == "UtteranceEnd":
            logger.debug("Deepgram: UtteranceEnd received")
        elif msg_type == "Error":
            logger.error("Deepgram error: %s", data)

"""
Deepgram pre-recorded transcription for human-agent calls.

Downloads the Twilio MP3 recording and sends it to Deepgram's REST API
with speaker diarization enabled. Returns a structured TranscriptionResult
with per-speaker turns ready for storage and GPT-4o analysis.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

DEEPGRAM_REST_URL = "https://api.deepgram.com/v1/listen"


@dataclass
class SpeakerTurn:
    speaker: int        # 0 = agent (first speaker), 1+ = borrower
    start_ms: int
    end_ms: int
    text: str
    confidence: float


@dataclass
class TranscriptionResult:
    raw_response: dict
    transcript_text: str                    # Human-readable "[Speaker 0]: ..."
    speaker_turns: list[SpeakerTurn] = field(default_factory=list)
    model_used: str = "nova-2"


class CallTranscriber:
    """
    Transcribes a completed call recording via Deepgram pre-recorded API.
    Uses speaker diarization to separate agent speech from borrower speech.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._deepgram_api_key = settings.deepgram_api_key
        self._model = settings.deepgram_model
        self._twilio_account_sid = settings.twilio_account_sid
        self._twilio_auth_token = settings.twilio_auth_token

    async def transcribe_recording(self, recording_url: str) -> TranscriptionResult:
        """
        Download recording from Twilio and transcribe with Deepgram.
        recording_url is the .mp3 URL stored in Call.recording_url.
        """
        logger.info("Downloading recording: %s", recording_url)
        audio_bytes = await self._download_recording(recording_url)
        logger.info("Downloaded %.1f KB — sending to Deepgram", len(audio_bytes) / 1024)
        return await self._transcribe(audio_bytes)

    async def _download_recording(self, url: str) -> bytes:
        """Download MP3 from Twilio. Requires Basic Auth (SID:token)."""
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(
                url,
                auth=(self._twilio_account_sid, self._twilio_auth_token),
            )
            response.raise_for_status()
            return response.content

    async def _transcribe(self, audio_bytes: bytes) -> TranscriptionResult:
        """POST audio bytes to Deepgram pre-recorded API with diarization."""
        params = {
            "model": self._model,
            "diarize": "true",
            "smart_format": "true",
            "punctuate": "true",
            "utterances": "true",
            "language": "en-IN",
        }
        headers = {
            "Authorization": f"Token {self._deepgram_api_key}",
            "Content-Type": "audio/mpeg",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                DEEPGRAM_REST_URL,
                content=audio_bytes,
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

        result = self._parse_response(data)
        logger.info(
            "Deepgram transcription complete: %d speaker turns, model=%s",
            len(result.speaker_turns), result.model_used,
        )
        return result

    def _parse_response(self, data: dict) -> TranscriptionResult:
        """
        Parse Deepgram utterances into SpeakerTurn list.
        Speaker index 0 → agent (first speaker), 1+ → borrower.
        """
        utterances = data.get("results", {}).get("utterances", [])
        speaker_turns: list[SpeakerTurn] = []
        text_lines: list[str] = []

        for u in utterances:
            speaker_idx = u.get("speaker", 0)
            text = u.get("transcript", "").strip()
            if not text:
                continue
            turn = SpeakerTurn(
                speaker=speaker_idx,
                start_ms=int(u.get("start", 0) * 1000),
                end_ms=int(u.get("end", 0) * 1000),
                text=text,
                confidence=float(u.get("confidence", 0.0)),
            )
            speaker_turns.append(turn)
            label = "Agent" if speaker_idx == 0 else "Borrower"
            text_lines.append(f"[{label}]: {text}")

        # Fallback: if utterances empty, use channel transcript
        if not speaker_turns:
            channels = data.get("results", {}).get("channels", [{}])
            fallback_text = channels[0].get("alternatives", [{}])[0].get("transcript", "")
            if fallback_text:
                text_lines = [f"[Unknown]: {fallback_text}"]

        return TranscriptionResult(
            raw_response=data,
            transcript_text="\n".join(text_lines),
            speaker_turns=speaker_turns,
            model_used=self._model,
        )

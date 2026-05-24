"""
TTS provider abstraction — common interface for all TTS backends.

All TTS providers must implement this interface. The session orchestrator
calls synthesize_stream() and doesn't care which backend is running.

Providers:
- ElevenLabs (eleven_turbo_v2) — proven, good quality, $0.30/1K chars
- Rumik Silk — expressive multi-Indic, ~300ms latency, emotional tags
- Edge TTS — free fallback (Microsoft)
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Optional

logger = logging.getLogger(__name__)


class TTSProvider(ABC):
    """Base interface for all TTS providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name for logging."""
        ...

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        chunk_size: int = 1024,
    ) -> AsyncGenerator[bytes, None]:
        """Stream synthesized speech as mulaw 8kHz chunks for Twilio.

        Args:
            text: Text to synthesize
            chunk_size: Hint for upstream chunk size (bytes)

        Yields:
            bytes: mulaw 8kHz audio chunks ready for Twilio Media Streams
        """
        ...

    async def pre_warm(self, text: str) -> None:
        """Pre-generate and cache TTS audio for zero-latency playback.

        Optional — providers that don't support caching can no-op.
        """
        pass

    async def close(self) -> None:
        """Clean up resources (WebSocket connections, etc.).

        Optional — providers that don't hold connections can no-op.
        """
        pass

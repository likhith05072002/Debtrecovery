"""
TTS provider factory — selects the right provider per-org or per-call.

Selection priority:
1. Explicit provider param (from campaign config or API call)
2. Organization-level setting (org.settings.tts_provider)
3. Language-based selection (Silk for Indic, ElevenLabs for others)
4. Global default (Silk if configured, else ElevenLabs)
"""
from __future__ import annotations

import logging

from app.config import get_settings
from app.services.tts.base import TTSProvider

logger = logging.getLogger(__name__)


def create_tts_provider(
    language: str = "en",
    provider: str | None = None,
    voice_id: str | None = None,
    use_websocket: bool = False,
) -> TTSProvider:
    """Create a TTS provider instance.

    Args:
        language: ISO language code (en, hi, kn, te, ta, ml, bn)
        provider: Explicit provider name ("silk", "elevenlabs", "edge")
        voice_id: Override voice ID (provider-specific)
        use_websocket: Use WebSocket client for lowest latency (Silk only)

    Returns:
        TTSProvider instance ready for synthesize_stream()
    """
    settings = get_settings()

    # Determine provider
    if provider is None:
        provider = _auto_select_provider(language, settings)

    if provider == "silk":
        if not settings.silk_api_key:
            logger.warning("Silk selected but no API key — falling back to ElevenLabs")
            provider = "elevenlabs"
        else:
            if use_websocket:
                from app.services.tts.silk_client import SilkWebSocketClient
                return SilkWebSocketClient(language=language, voice_id=voice_id)
            else:
                from app.services.tts.silk_client import SilkTTSClient
                return SilkTTSClient(language=language, voice_id=voice_id)

    if provider == "elevenlabs":
        from app.services.tts.elevenlabs_client import ElevenLabsTTSClient
        return ElevenLabsTTSClient(language=language)

    # Unknown provider — default to ElevenLabs
    logger.warning("Unknown TTS provider '%s', using ElevenLabs", provider)
    from app.services.tts.elevenlabs_client import ElevenLabsTTSClient
    return ElevenLabsTTSClient(language=language)


def _auto_select_provider(language: str, settings) -> str:
    """Auto-select TTS provider based on language and configuration.

    Logic:
    - If Silk API key is set → prefer Silk (especially for Indic languages)
    - Otherwise → ElevenLabs
    """
    if settings.silk_api_key:
        # Silk has native Indic support — always prefer for these languages
        # For English, Silk is also fine (trained on multi-lingual data)
        return "silk"

    return "elevenlabs"

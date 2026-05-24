from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = "insecure-dev-key-change-in-prod"
    agency_name: str = "Apex Recovery Services"
    agent_name: str = "Alex"

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/debtcollector"
    database_pool_size: int = 20
    database_max_overflow: int = 10

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Twilio ────────────────────────────────────────────────────────────────
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = "+12138387179"
    twilio_webhook_base_url: str = "https://your-domain.com"
    # Twilio Client SDK (browser calling) — create at console.twilio.com → API Keys
    twilio_api_key_sid: str = ""
    twilio_api_key_secret: str = ""
    # TwiML App SID — create at console.twilio.com → Voice → TwiML Apps
    # Voice URL must point to: {your_domain}/api/v1/telephony/voice_client
    twilio_twiml_app_sid: str = ""

    # ── Deepgram (STT) ────────────────────────────────────────────────────────
    deepgram_api_key: str = ""
    deepgram_model: str = "nova-2"
    deepgram_endpointing_ms: int = 50

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_llm_model: str = "gpt-4o"
    openai_llm_max_tokens: int = 150
    openai_llm_temperature: float = 0.4
    # Fast model for first-sentence generation (lower TTFT)
    openai_fast_model: str = "gpt-4o-mini"
    openai_fast_max_tokens: int = 60

    # ── ElevenLabs (TTS) ─────────────────────────────────────────────────────
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    elevenlabs_model_id: str = "eleven_turbo_v2"
    elevenlabs_stability: float = 0.5
    elevenlabs_similarity_boost: float = 0.75

    # ── Rumik Silk (TTS) ─────────────────────────────────────────────────────
    silk_api_key: str = ""
    silk_model_id: str = "silk-v1"
    silk_sample_rate: int = 24000              # 24000 or 16000
    silk_default_voice: str = "silk-en-male-professional"
    tts_provider: str = "auto"                 # "silk" | "elevenlabs" | "auto"

    # ── Vector Store ──────────────────────────────────────────────────────────
    vector_store_path: str = "./ml/vector_store"
    vector_embedding_model: str = "text-embedding-3-small"
    vector_top_k: int = 3

    # ── Compliance / FDCPA ────────────────────────────────────────────────────
    fdcpa_call_window_start: int = 8   # 8 AM local borrower time
    fdcpa_call_window_end: int = 21    # 9 PM local borrower time
    fdcpa_max_calls_per_day: int = 1
    fdcpa_max_calls_per_week: int = 3
    fdcpa_max_calls_per_month: int = 12

    # ── PII Encryption ────────────────────────────────────────────────────────
    pii_encryption_key: str = ""   # Fernet key, base64-encoded 32 bytes

    # ── JWT / Auth ────────────────────────────────────────────────────────────
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    # ── Stripe (Billing) ─────────────────────────────────────────────────────
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id_starter: str = ""
    stripe_price_id_growth: str = ""

    # ── Email (SendGrid) ─────────────────────────────────────────────────────
    sendgrid_api_key: str = ""
    email_from_address: str = "noreply@debtcollector.ai"
    email_from_name: str = "DebtCollector"

    # ── Monitoring ────────────────────────────────────────────────────────────
    prometheus_enabled: bool = True
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    # ── ML ────────────────────────────────────────────────────────────────────
    ml_models_path: str = "./ml/models"
    ml_strategy_model_file: str = "strategy_model.pkl"
    ml_model_refresh_interval_seconds: int = 3600

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def websocket_url(self) -> str:
        base = self.twilio_webhook_base_url.replace("https://", "wss://").replace("http://", "ws://")
        return base


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

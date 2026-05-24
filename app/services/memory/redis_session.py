"""
Redis short-term session store for live call state.

All call-critical state lives here during a call so that the API layer
remains stateless (any pod can handle any call).

Key patterns:
  session:{call_sid}           — call session hash
  session:{call_sid}:history   — conversation turn list (capped at 200)
  borrower:{borrower_id}:profile — cached borrower profile (TTL 1h)
  ratelimit:{borrower_id}:daily — FDCPA daily call cap counter
  ratelimit:{borrower_id}:weekly — FDCPA weekly call cap counter
  dnc:{phone_hash}             — Do-Not-Call flag (no expiry)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

SESSION_TTL = 3600          # 1 hour — calls longer than this are unusual
BORROWER_CACHE_TTL = 3600   # 1 hour
HISTORY_MAX_TURNS = 200     # Full call transcript — never trim during a call


def _get_redis() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(settings.redis_url, decode_responses=True)


class RedisSessionManager:
    """Manages all Redis keys for a single live call session."""

    def __init__(self, call_sid: str) -> None:
        self.call_sid = call_sid
        self._key = f"session:{call_sid}"
        self._history_key = f"session:{call_sid}:history"
        self._r = _get_redis()

    # ── Session lifecycle ─────────────────────────────────────────────────────

    async def create(
        self,
        borrower_id: str,
        strategy: str,
        stream_sid: str = "",
    ) -> None:
        """Initialize a new call session in Redis."""
        data = {
            "call_sid": self.call_sid,
            "borrower_id": borrower_id,
            "stream_sid": stream_sid,
            "state": "greeting",
            "strategy": strategy,
            "agent_speaking": "false",
            "turn_count": "0",
            "mini_miranda_delivered": "false",
            "recording_consent": "false",
            "current_offer": "{}",
            "sentiment_window": "[]",
            "entities_extracted": json.dumps({
                "payment_dates_mentioned": [],
                "amounts_mentioned": [],
                "hardship_signals": [],
            }),
            "compliance_flags": "[]",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_activity_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._r.hmset(self._key, data)
        await self._r.expire(self._key, SESSION_TTL)
        await self._r.expire(self._history_key, SESSION_TTL)

    async def get(self, field: str) -> Optional[str]:
        return await self._r.hget(self._key, field)

    async def set(self, field: str, value: Any) -> None:
        v = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        await self._r.hset(self._key, field, v)
        await self._r.hset(self._key, "last_activity_at", datetime.now(timezone.utc).isoformat())

    async def get_all(self) -> dict:
        return await self._r.hgetall(self._key)

    async def delete(self) -> None:
        await self._r.delete(self._key, self._history_key)

    # ── Conversation history ──────────────────────────────────────────────────

    async def append_turn(self, turn: dict) -> None:
        """Append a conversation turn to the session history (capped at 30)."""
        await self._r.rpush(self._history_key, json.dumps(turn))
        # Keep only the last N turns to bound memory usage
        length = await self._r.llen(self._history_key)
        if length > HISTORY_MAX_TURNS:
            await self._r.ltrim(self._history_key, length - HISTORY_MAX_TURNS, -1)
        await self._r.expire(self._history_key, SESSION_TTL)

    async def get_history(self) -> list[dict]:
        """Return all conversation turns as a list of dicts."""
        raw = await self._r.lrange(self._history_key, 0, -1)
        result = []
        for item in raw:
            try:
                result.append(json.loads(item))
            except json.JSONDecodeError:
                pass
        return result

    # ── Convenience properties ────────────────────────────────────────────────

    async def is_agent_speaking(self) -> bool:
        v = await self.get("agent_speaking")
        return v == "true"

    async def set_agent_speaking(self, speaking: bool) -> None:
        await self.set("agent_speaking", "true" if speaking else "false")
        if speaking:
            # Set a TTL-based safety key — if process crashes while speaking,
            # this expires in 10s and is_agent_speaking will return False.
            await self._r.setex(f"{self._key}:speaking_guard", 10, "1")
        else:
            await self._r.delete(f"{self._key}:speaking_guard")

    async def is_agent_speaking_safe(self) -> bool:
        """Crash-safe check: returns False if speaking_guard has expired (process crashed)."""
        guard = await self._r.exists(f"{self._key}:speaking_guard")
        if not guard:
            # Guard expired — force reset stale speaking state
            v = await self.get("agent_speaking")
            if v == "true":
                await self.set("agent_speaking", "false")
            return False
        return await self.is_agent_speaking()

    async def get_state(self) -> str:
        return (await self.get("state")) or "greeting"

    async def set_state(self, state: str) -> None:
        await self.set("state", state)

    async def increment_turn(self) -> int:
        new_count = await self._r.hincrby(self._key, "turn_count", 1)
        return int(new_count)

    async def mark_mini_miranda_delivered(self) -> None:
        await self.set("mini_miranda_delivered", "true")

    async def is_mini_miranda_delivered(self) -> bool:
        v = await self.get("mini_miranda_delivered")
        return v == "true"


# ── Borrower profile cache ────────────────────────────────────────────────────

async def cache_borrower_profile(borrower_id: str, profile: dict) -> None:
    r = _get_redis()
    key = f"borrower:{borrower_id}:profile"
    await r.set(key, json.dumps(profile), ex=BORROWER_CACHE_TTL)


async def get_cached_borrower_profile(borrower_id: str) -> Optional[dict]:
    r = _get_redis()
    key = f"borrower:{borrower_id}:profile"
    raw = await r.get(key)
    if raw:
        return json.loads(raw)
    return None


# ── DNC (Do-Not-Call) Redis helpers ──────────────────────────────────────────

async def set_dnc(phone_hash: str) -> None:
    """Mark a phone number as Do-Not-Call. Permanent (no TTL)."""
    r = _get_redis()
    await r.set(f"dnc:{phone_hash}", "1")


async def is_dnc(phone_hash: str) -> bool:
    r = _get_redis()
    return await r.exists(f"dnc:{phone_hash}") == 1


async def set_call_setup_metadata(call_sid: str, metadata: dict[str, Any], ttl_seconds: int = 3600) -> None:
    r = _get_redis()
    await r.set(f"callsetup:{call_sid}", json.dumps(metadata), ex=ttl_seconds)


async def get_call_setup_metadata(call_sid: str) -> Optional[dict[str, Any]]:
    r = _get_redis()
    raw = await r.get(f"callsetup:{call_sid}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ── FDCPA frequency rate limits ───────────────────────────────────────────────

async def check_and_increment_call_count(
    borrower_id: str,
    max_daily: int,
    max_weekly: int,
) -> tuple[bool, str]:
    """
    Returns (allowed, reason).
    Increments counters only if the call is allowed.
    """
    r = _get_redis()
    daily_key = f"ratelimit:{borrower_id}:daily"
    weekly_key = f"ratelimit:{borrower_id}:weekly"

    daily = int(await r.get(daily_key) or 0)
    weekly = int(await r.get(weekly_key) or 0)

    if daily >= max_daily:
        return False, f"Daily cap exceeded ({daily}/{max_daily})"
    if weekly >= max_weekly:
        return False, f"Weekly cap exceeded ({weekly}/{max_weekly})"

    # Atomically increment
    pipe = r.pipeline()
    pipe.incr(daily_key)
    pipe.expire(daily_key, 86400)    # 24h TTL
    pipe.incr(weekly_key)
    pipe.expire(weekly_key, 604800)  # 7d TTL
    await pipe.execute()

    return True, "ok"

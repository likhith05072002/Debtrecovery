"""
Conversation manager — maintains the in-memory dialogue state for a live call
and assembles the GPT message history from Redis session turns.
"""
from __future__ import annotations

from typing import Optional

from app.services.memory.redis_session import RedisSessionManager


class ConversationManager:
    """
    Assembles the messages list for GPT-4o from the Redis session history.
    Keeps the history bounded to prevent token overflow.
    """

    MAX_HISTORY_TURNS = 20   # Trim to last 20 turns for context window management

    def __init__(self, session: RedisSessionManager) -> None:
        self._session = session

    async def get_gpt_messages(self) -> list[dict]:
        """
        Return conversation history formatted for the OpenAI messages API.
        Trims to MAX_HISTORY_TURNS most recent turns.
        """
        turns = await self._session.get_history()
        messages = []
        for turn in turns[-self.MAX_HISTORY_TURNS:]:
            role = "assistant" if turn.get("speaker") == "agent" else "user"
            text = turn.get("text", "")
            if text:
                messages.append({"role": role, "content": text})
        return messages

    async def add_agent_turn(self, text: str, intent: Optional[str] = None) -> None:
        await self._session.append_turn({
            "speaker": "agent",
            "text": text,
            "intent": intent or "response",
        })

    async def add_borrower_turn(
        self,
        text: str,
        confidence: float,
        intent: Optional[str] = None,
        sentiment: Optional[float] = None,
        entities: Optional[dict] = None,
    ) -> None:
        await self._session.append_turn({
            "speaker": "borrower",
            "text": text,
            "confidence": confidence,
            "intent": intent,
            "sentiment": sentiment,
            "entities": entities or {},
        })

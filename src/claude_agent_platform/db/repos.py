"""Platform DB repositories."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from claude_agent_platform.db.models import AgentChat, AgentMessage, PlatformUser


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_dev_user(self, email: str) -> PlatformUser:
        result = await self._session.execute(
            select(PlatformUser).where(PlatformUser.email == email)
        )
        user = result.scalar_one_or_none()
        if user:
            return user
        user = PlatformUser(email=email)
        self._session.add(user)
        await self._session.flush()
        return user


class ChatRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        agent_type: str,
        title: str | None = None,
    ) -> AgentChat:
        chat = AgentChat(user_id=user_id, agent_type=agent_type, title=title)
        self._session.add(chat)
        await self._session.flush()
        return chat

    async def get(self, chat_id: uuid.UUID) -> AgentChat | None:
        result = await self._session.execute(select(AgentChat).where(AgentChat.id == chat_id))
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, agent_type: str, *, limit: int = 50
    ) -> list[AgentChat]:
        result = await self._session.execute(
            select(AgentChat)
            .where(AgentChat.user_id == user_id, AgentChat.agent_type == agent_type)
            .order_by(AgentChat.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_sdk_session_id(self, chat_id: uuid.UUID, session_id: str) -> None:
        await self._session.execute(
            update(AgentChat)
            .where(AgentChat.id == chat_id)
            .values(sdk_session_id=session_id, updated_at=func.now())
        )

    async def increment_totals(
        self,
        chat_id: uuid.UUID,
        usage: dict[str, Any],
        cost_usd: float | None,
    ) -> None:
        cost = Decimal(str(cost_usd or 0))
        await self._session.execute(
            update(AgentChat)
            .where(AgentChat.id == chat_id)
            .values(
                total_input_tokens=AgentChat.total_input_tokens + usage.get("input_tokens", 0),
                total_output_tokens=AgentChat.total_output_tokens + usage.get("output_tokens", 0),
                total_cache_read_input_tokens=AgentChat.total_cache_read_input_tokens
                + usage.get("cache_read_input_tokens", 0),
                total_cache_creation_input_tokens=AgentChat.total_cache_creation_input_tokens
                + usage.get("cache_creation_input_tokens", 0),
                total_cost_usd=AgentChat.total_cost_usd + cost,
                updated_at=func.now(),
            )
        )


class MessageRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_seq(self, chat_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.max(AgentMessage.seq), 0)).where(
                AgentMessage.chat_id == chat_id
            )
        )
        current = result.scalar_one()
        return int(current) + 1

    async def insert(
        self,
        *,
        chat_id: uuid.UUID,
        seq: int,
        sdk_type: str,
        payload: dict[str, Any],
        turn_stats: dict[str, Any] | None = None,
    ) -> AgentMessage:
        msg = AgentMessage(
            chat_id=chat_id,
            seq=seq,
            sdk_type=sdk_type,
            payload=payload,
        )
        if turn_stats:
            msg.turn_input_tokens = turn_stats.get("input_tokens")
            msg.turn_output_tokens = turn_stats.get("output_tokens")
            msg.turn_cache_read_input_tokens = turn_stats.get("cache_read_input_tokens")
            msg.turn_cache_creation_input_tokens = turn_stats.get("cache_creation_input_tokens")
            cost = turn_stats.get("cost_usd")
            msg.turn_cost_usd = Decimal(str(cost)) if cost is not None else None
        self._session.add(msg)
        await self._session.flush()
        return msg

    async def list_for_chat(self, chat_id: uuid.UUID) -> list[AgentMessage]:
        result = await self._session.execute(
            select(AgentMessage)
            .where(AgentMessage.chat_id == chat_id)
            .order_by(AgentMessage.seq)
        )
        return list(result.scalars().all())

    async def get_recent_turn_payloads(
        self, chat_id: uuid.UUID, max_turns: int
    ) -> list[list[dict[str, Any]]]:
        """Group messages by turn (each turn ends at result). Returns last N turns."""
        messages = await self.list_for_chat(chat_id)
        turns: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for msg in messages:
            current.append(msg.payload)
            if msg.sdk_type == "result":
                turns.append(current)
                current = []
        if current:
            turns.append(current)
        return turns[-max_turns:]

"""Redis working set for memory frames."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from claude_agent_platform.config import get_settings


class RedisMemoryStore:
    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def _ws_key(self, agent_type: str, chat_id: str) -> str:
        return f"{agent_type}:{chat_id}:working_set"

    def _meta_key(self, agent_type: str, chat_id: str) -> str:
        return f"{agent_type}:{chat_id}:meta"

    async def append_frame(
        self,
        agent_type: str,
        chat_id: str,
        frame: dict[str, Any],
        *,
        ttl_hours: int,
        max_turns: int,
    ) -> None:
        key = self._ws_key(agent_type, chat_id)
        raw = await self._client.get(key)
        frames: list[dict[str, Any]] = json.loads(raw) if raw else []
        frames.append(frame)
        frames = frames[-max_turns:]
        ttl = ttl_hours * 3600
        await self._client.set(key, json.dumps(frames, ensure_ascii=False), ex=ttl)

    async def get_frames(self, agent_type: str, chat_id: str) -> list[dict[str, Any]] | None:
        raw = await self._client.get(self._ws_key(agent_type, chat_id))
        if not raw:
            return None
        return json.loads(raw)

    async def set_meta(
        self, agent_type: str, chat_id: str, sdk_session_id: str, turn_count: int, *, ttl_hours: int
    ) -> None:
        key = self._meta_key(agent_type, chat_id)
        await self._client.set(
            key,
            json.dumps({"sdk_session_id": sdk_session_id, "turn_count": turn_count}),
            ex=ttl_hours * 3600,
        )


_store: RedisMemoryStore | None = None


async def init_redis() -> RedisMemoryStore:
    global _store
    settings = get_settings()
    client = redis.from_url(settings.redis_url, decode_responses=True)
    _store = RedisMemoryStore(client)
    return _store


def get_redis_store() -> RedisMemoryStore:
    if _store is None:
        raise RuntimeError("Redis not initialized")
    return _store


async def close_redis() -> None:
    global _store
    if _store and _store._client:
        await _store._client.aclose()
        _store = None

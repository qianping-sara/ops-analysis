"""Per-chat ClaudeSDKClient pool."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from claude_agent_platform.config import get_settings


@dataclass
class PooledClient:
    client: ClaudeSDKClient
    options: ClaudeAgentOptions
    last_used: float


class ClientPool:
    def __init__(self) -> None:
        self._clients: dict[tuple[str, uuid.UUID], PooledClient] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        agent_type: str,
        chat_id: uuid.UUID,
        options: ClaudeAgentOptions,
        *,
        force_new: bool = False,
    ) -> tuple[ClaudeSDKClient, bool]:
        """Returns (client, created_new)."""
        key = (agent_type, chat_id)
        settings = get_settings()
        async with self._lock:
            if not force_new and key in self._clients:
                pooled = self._clients[key]
                if time.time() - pooled.last_used < settings.client_idle_seconds:
                    pooled.last_used = time.time()
                    return pooled.client, False
                await self._disconnect(pooled.client)
                del self._clients[key]

            client = ClaudeSDKClient(options=options)
            await client.connect()
            self._clients[key] = PooledClient(client=client, options=options, last_used=time.time())
            return client, True

    async def touch(self, agent_type: str, chat_id: uuid.UUID) -> None:
        key = (agent_type, chat_id)
        if key in self._clients:
            self._clients[key].last_used = time.time()

    async def remove(self, agent_type: str, chat_id: uuid.UUID) -> None:
        key = (agent_type, chat_id)
        async with self._lock:
            if key in self._clients:
                await self._disconnect(self._clients[key].client)
                del self._clients[key]

    async def close_all(self) -> None:
        async with self._lock:
            for pooled in self._clients.values():
                await self._disconnect(pooled.client)
            self._clients.clear()

    @staticmethod
    async def _disconnect(client: ClaudeSDKClient) -> None:
        try:
            await client.disconnect()
        except Exception:
            pass


_pool: ClientPool | None = None


def get_client_pool() -> ClientPool:
    global _pool
    if _pool is None:
        _pool = ClientPool()
    return _pool

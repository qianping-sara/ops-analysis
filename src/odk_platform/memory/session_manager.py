"""Session manager: hot resume vs cold continue."""

from __future__ import annotations

import uuid
from typing import Any

from odk_platform.core.options_builder import build_options, wrap_user_message
from odk_platform.core.profile import AgentProfile
from odk_platform.db.repos import MessageRepo
from odk_platform.memory.context_builder import build_cold_prefix
from odk_platform.memory.projectors.registry import MemoryProjectorRegistry, build_default_registry
from odk_platform.memory.redis_store import RedisMemoryStore
from odk_platform.memory.turn_memory_compactor import compact_turn


class SessionManager:
    def __init__(self, registry: MemoryProjectorRegistry | None = None) -> None:
        self._registry = registry or build_default_registry()

    async def prepare_turn(
        self,
        profile: AgentProfile,
        chat_id: uuid.UUID,
        user_message: str,
        *,
        sdk_session_id: str | None,
        message_repo: MessageRepo,
        redis_store: RedisMemoryStore | None,
        client_alive: bool,
    ) -> tuple[Any, str, bool]:
        """Returns (ClaudeAgentOptions, wrapped_user_message, is_cold)."""
        cold_prefix: str | None = None
        is_cold = False
        resume: str | None = None

        if client_alive:
            pass  # same client — no resume, no cold prefix
        elif sdk_session_id:
            resume = sdk_session_id
        else:
            turns = await message_repo.get_recent_turn_payloads(chat_id, 1)
            if turns:
                is_cold = True
                frames = await self._load_frames(
                    profile, chat_id, message_repo, redis_store
                )
                cold_prefix = build_cold_prefix(
                    frames,
                    max_tokens=profile.memory.cold_resume_max_tokens,
                )

        opts = build_options(profile, resume=resume, cold_prefix=cold_prefix)
        wrapped = wrap_user_message(user_message, cold_prefix)
        return opts, wrapped, is_cold

    async def _load_frames(
        self,
        profile: AgentProfile,
        chat_id: uuid.UUID,
        message_repo: MessageRepo,
        redis_store: RedisMemoryStore | None,
    ) -> list[dict[str, Any]]:
        if redis_store and profile.memory.enabled:
            cached = await redis_store.get_frames(profile.id, str(chat_id))
            if cached:
                return cached

        turns = await message_repo.get_recent_turn_payloads(
            chat_id, profile.memory.cold_resume_max_turns
        )
        frames = []
        base = max(0, len(turns) - profile.memory.cold_resume_max_turns)
        for idx, turn in enumerate(turns):
            frames.append(compact_turn(turn, self._registry, turn_index=base + idx + 1))
        return frames

    async def on_turn_complete(
        self,
        profile: AgentProfile,
        chat_id: uuid.UUID,
        turn_payloads: list[dict[str, Any]],
        *,
        redis_store: RedisMemoryStore | None,
        turn_index: int,
    ) -> None:
        if not profile.memory.enabled or not redis_store:
            return
        frame = compact_turn(turn_payloads, self._registry, turn_index=turn_index)
        await redis_store.append_frame(
            profile.id,
            str(chat_id),
            frame,
            ttl_hours=profile.memory.ttl_hours,
            max_turns=profile.memory.working_set_turns,
        )

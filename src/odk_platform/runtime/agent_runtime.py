"""Agent turn execution with SSE event generation."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from odk_platform.core.profile import AgentProfile
from odk_platform.core.registry import get_registry
from odk_platform.db.repos import ChatRepo, MessageRepo
from odk_platform.memory.redis_store import RedisMemoryStore
from odk_platform.memory.session_manager import SessionManager
from odk_platform.runtime.client_pool import get_client_pool
from odk_platform.runtime.sdk_serializer import extract_session_id, sdk_type_name, serialize_message


class AgentRuntime:
    def __init__(self) -> None:
        self._session_manager = SessionManager()

    async def run_turn(
        self,
        *,
        agent_type: str,
        chat_id: uuid.UUID,
        user_message: str,
        chat_repo: ChatRepo,
        message_repo: MessageRepo,
        redis_store: RedisMemoryStore | None,
    ) -> AsyncIterator[dict[str, Any]]:
        profile = get_registry().get(agent_type)
        chat = await chat_repo.get(chat_id)
        if not chat:
            yield {"type": "error", "message": "Chat not found"}
            return

        pool = get_client_pool()
        key_alive = (agent_type, chat_id) in pool._clients  # noqa: SLF001

        opts, wrapped_message, is_cold = await self._session_manager.prepare_turn(
            profile,
            chat_id,
            user_message,
            sdk_session_id=chat.sdk_session_id,
            message_repo=message_repo,
            redis_store=redis_store,
            client_alive=key_alive,
        )

        force_new = is_cold or (not key_alive and bool(chat.sdk_session_id))
        client, _ = await pool.get_or_create(agent_type, chat_id, opts, force_new=force_new)

        turn_payloads: list[dict[str, Any]] = []
        seq = await message_repo.next_seq(chat_id)

        # Persist user message
        user_payload = {"type": "user", "content": user_message}
        await message_repo.insert(chat_id=chat_id, seq=seq, sdk_type="user", payload=user_payload)
        turn_payloads.append(user_payload)
        seq += 1

        try:
            await client.query(wrapped_message)
            async for message in client.receive_response():
                payload = serialize_message(message)
                stype = sdk_type_name(message)

                turn_stats = None
                if isinstance(message, ResultMessage):
                    usage = message.usage or {}
                    usage_dict = usage if isinstance(usage, dict) else dict(usage)
                    turn_stats = {
                        "input_tokens": usage_dict.get("input_tokens", 0),
                        "output_tokens": usage_dict.get("output_tokens", 0),
                        "cache_read_input_tokens": usage_dict.get("cache_read_input_tokens", 0),
                        "cache_creation_input_tokens": usage_dict.get(
                            "cache_creation_input_tokens", 0
                        ),
                        "cost_usd": float(message.total_cost_usd or 0),
                    }

                await message_repo.insert(
                    chat_id=chat_id,
                    seq=seq,
                    sdk_type=stype,
                    payload=payload,
                    turn_stats=turn_stats,
                )
                turn_payloads.append(payload)
                seq += 1

                sid = extract_session_id(message)
                if sid:
                    await chat_repo.update_sdk_session_id(chat_id, sid)

                for event in _message_to_sse(message):
                    yield event

                if isinstance(message, ResultMessage):
                    usage_dict = turn_stats or {}
                    await chat_repo.increment_totals(
                        chat_id,
                        {
                            "input_tokens": usage_dict.get("input_tokens", 0),
                            "output_tokens": usage_dict.get("output_tokens", 0),
                            "cache_read_input_tokens": usage_dict.get(
                                "cache_read_input_tokens", 0
                            ),
                            "cache_creation_input_tokens": usage_dict.get(
                                "cache_creation_input_tokens", 0
                            ),
                        },
                        usage_dict.get("cost_usd"),
                    )

                    yield {
                        "type": "usage",
                        "input_tokens": usage_dict.get("input_tokens", 0),
                        "output_tokens": usage_dict.get("output_tokens", 0),
                        "cache_read_input_tokens": usage_dict.get(
                            "cache_read_input_tokens", 0
                        ),
                        "cache_creation_input_tokens": usage_dict.get(
                            "cache_creation_input_tokens", 0
                        ),
                        "cost_usd": usage_dict.get("cost_usd", 0),
                    }

                    prior_results = await message_repo.list_for_chat(chat_id)
                    turn_count = sum(1 for m in prior_results if m.sdk_type == "result")
                    await self._session_manager.on_turn_complete(
                        profile,
                        chat_id,
                        turn_payloads,
                        redis_store=redis_store,
                        turn_index=turn_count,
                    )

            await pool.touch(agent_type, chat_id)
            yield {"type": "done", "chat_id": str(chat_id)}

        except Exception as exc:
            yield {"type": "error", "message": str(exc)}
            await pool.remove(agent_type, chat_id)


def _message_to_sse(message: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                events.append({"type": "text_delta", "content": block.text})
            elif isinstance(block, ToolUseBlock):
                events.append(
                    {
                        "type": "tool_use",
                        "tool": block.name,
                        "input": block.input,
                    }
                )
    return events

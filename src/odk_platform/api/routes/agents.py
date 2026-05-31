"""Agent API routes."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from odk_platform.api.deps import get_dev_user, get_session
from odk_platform.core.registry import get_registry
from odk_platform.db.models import PlatformUser
from odk_platform.db.repos import ChatRepo, MessageRepo
from odk_platform.memory.redis_store import get_redis_store
from odk_platform.runtime.agent_runtime import AgentRuntime
from odk_platform.runtime.message_presenter import present_messages

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])
_runtime = AgentRuntime()


class CreateChatBody(BaseModel):
    title: str | None = None


class SendMessageBody(BaseModel):
    content: str


@router.get("")
async def list_agents() -> dict[str, Any]:
    agents = get_registry().list_agents()
    return {
        "agents": [
            {"id": a.id, "name": a.name, "description": a.description, "version": a.version}
            for a in agents
        ]
    }


@router.get("/{agent_type}")
async def get_agent(agent_type: str) -> dict[str, Any]:
    try:
        profile = get_registry().get(agent_type)
    except KeyError as exc:
        raise HTTPException(404, "Agent not found") from exc
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "version": profile.version,
        "model": profile.model,
    }


@router.post("/{agent_type}/chats")
async def create_chat(
    agent_type: str,
    body: CreateChatBody,
    user: PlatformUser = Depends(get_dev_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        get_registry().get(agent_type)
    except KeyError as exc:
        raise HTTPException(404, "Agent not found") from exc

    repo = ChatRepo(session)
    chat = await repo.create(user_id=user.id, agent_type=agent_type, title=body.title)
    await session.commit()
    return _chat_dict(chat)


@router.get("/{agent_type}/chats")
async def list_chats(
    agent_type: str,
    user: PlatformUser = Depends(get_dev_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        get_registry().get(agent_type)
    except KeyError as exc:
        raise HTTPException(404, "Agent not found") from exc

    repo = ChatRepo(session)
    chats = await repo.list_for_user(user.id, agent_type)
    return {"chats": [_chat_dict(c) for c in chats]}


@router.get("/{agent_type}/chats/{chat_id}")
async def get_chat(
    agent_type: str,
    chat_id: uuid.UUID,
    user: PlatformUser = Depends(get_dev_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    chat = await _get_chat_or_404(session, agent_type, chat_id, user.id)
    return _chat_dict(chat)


@router.get("/{agent_type}/chats/{chat_id}/messages")
async def get_messages(
    agent_type: str,
    chat_id: uuid.UUID,
    user: PlatformUser = Depends(get_dev_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _get_chat_or_404(session, agent_type, chat_id, user.id)
    repo = MessageRepo(session)
    messages = await repo.list_for_chat(chat_id)
    payloads = [m.payload for m in messages]
    return {"messages": present_messages(payloads)}


@router.post("/{agent_type}/chats/{chat_id}/messages")
async def send_message(
    agent_type: str,
    chat_id: uuid.UUID,
    body: SendMessageBody,
    user: PlatformUser = Depends(get_dev_user),
    session: AsyncSession = Depends(get_session),
):
    await _get_chat_or_404(session, agent_type, chat_id, user.id)
    chat_repo = ChatRepo(session)
    message_repo = MessageRepo(session)

    try:
        redis_store = get_redis_store()
    except RuntimeError:
        redis_store = None

    async def event_generator():
        try:
            async for event in _runtime.run_turn(
                agent_type=agent_type,
                chat_id=chat_id,
                user_message=body.content,
                chat_repo=chat_repo,
                message_repo=message_repo,
                redis_store=redis_store,
            ):
                yield {
                    "event": event.get("type", "message"),
                    "data": json.dumps(event, ensure_ascii=False),
                }
            await session.commit()
        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"type": "error", "message": str(exc)})}
            await session.rollback()

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _get_chat_or_404(
    session: AsyncSession, agent_type: str, chat_id: uuid.UUID, user_id: uuid.UUID
):
    try:
        get_registry().get(agent_type)
    except KeyError as exc:
        raise HTTPException(404, "Agent not found") from exc

    repo = ChatRepo(session)
    chat = await repo.get(chat_id)
    if not chat or chat.user_id != user_id or chat.agent_type != agent_type:
        raise HTTPException(404, "Chat not found")
    return chat


def _chat_dict(chat) -> dict[str, Any]:
    return {
        "id": str(chat.id),
        "agent_type": chat.agent_type,
        "title": chat.title,
        "sdk_session_id": chat.sdk_session_id,
        "total_input_tokens": chat.total_input_tokens,
        "total_output_tokens": chat.total_output_tokens,
        "total_cost_usd": float(chat.total_cost_usd or 0),
        "created_at": chat.created_at.isoformat() if chat.created_at else None,
        "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
    }

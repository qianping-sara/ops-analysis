"""Serialize / deserialize Claude Agent SDK messages."""

from __future__ import annotations

import dataclasses
from typing import Any

from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)


def sdk_type_name(message: Any) -> str:
    if isinstance(message, UserMessage):
        return "user"
    if isinstance(message, AssistantMessage):
        return "assistant"
    if isinstance(message, SystemMessage):
        return "system"
    if isinstance(message, ResultMessage):
        return "result"
    return type(message).__name__.lower()


def serialize_message(message: Any) -> dict[str, Any]:
    if isinstance(message, UserMessage):
        return {"type": "user", ** _user_payload(message)}
    if isinstance(message, AssistantMessage):
        return {"type": "assistant", "content": _serialize_content(message.content)}
    if isinstance(message, SystemMessage):
        return {
            "type": "system",
            "subtype": message.subtype,
            "data": message.data if hasattr(message, "data") else {},
        }
    if isinstance(message, ResultMessage):
        usage = message.usage or {}
        return {
            "type": "result",
            "subtype": message.subtype,
            "result": message.result,
            "usage": usage if isinstance(usage, dict) else dataclasses.asdict(usage),
            "total_cost_usd": message.total_cost_usd,
            "session_id": message.session_id,
        }
    if dataclasses.is_dataclass(message):
        return dataclasses.asdict(message)
    return {"type": "unknown", "raw": str(message)}


def _user_payload(message: UserMessage) -> dict[str, Any]:
    content = message.content
    if isinstance(content, str):
        return {"content": content}
    return {"content": _serialize_content(content)}


def _serialize_content(content: Any) -> list[dict[str, Any]] | str:
    if isinstance(content, str):
        return content
    blocks: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, TextBlock):
            blocks.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolUseBlock):
            blocks.append(
                {
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                }
            )
        elif isinstance(block, ToolResultBlock):
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content,
                }
            )
        elif isinstance(block, dict):
            blocks.append(block)
        else:
            blocks.append({"type": "unknown", "raw": str(block)})
    return blocks


def extract_session_id(message: Any) -> str | None:
    if isinstance(message, SystemMessage) and message.subtype == "init":
        data = message.data or {}
        return data.get("session_id")
    if isinstance(message, ResultMessage):
        return message.session_id
    if hasattr(message, "session_id"):
        sid = getattr(message, "session_id", None)
        return sid if isinstance(sid, str) else None
    return None

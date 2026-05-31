"""Map Claude Agent SDK messages / stream events to platform SSE payloads."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_sdk.types import (
    AssistantMessage,
    StreamEvent,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

_TOOL_RESULT_SSE_MAX = 12_000


def stream_event_to_sse(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse Anthropic-style stream_event payloads into UI SSE events."""
    out: list[dict[str, Any]] = []
    etype = event.get("type")

    if etype == "content_block_delta":
        delta = event.get("delta") or {}
        dtype = delta.get("type")
        if dtype == "text_delta":
            text = delta.get("text") or ""
            if text:
                out.append({"type": "text_delta", "content": text})
        elif dtype == "thinking_delta":
            thinking = delta.get("thinking") or ""
            if thinking:
                out.append({"type": "thinking_delta", "content": thinking})
        elif dtype == "input_json_delta":
            partial = delta.get("partial_json") or ""
            if partial:
                idx = event.get("index")
                out.append(
                    {
                        "type": "tool_input_delta",
                        "index": idx,
                        "partial_json": partial,
                    }
                )
    elif etype == "content_block_start":
        block = event.get("content_block") or {}
        if block.get("type") == "tool_use":
            out.append(_tool_use_event(block))
    elif etype == "message_delta":
        delta = event.get("delta") or {}
        if delta.get("type") == "text_delta":
            text = delta.get("text") or ""
            if text:
                out.append({"type": "text_delta", "content": text})

    return out


def message_to_sse(
    message: Any,
    *,
    skip_text: bool = False,
    emitted_tool_ids: set[str] | None = None,
    emitted_thinking: bool = False,
) -> tuple[list[dict[str, Any]], bool, set[str], bool]:
    """
    Convert a completed SDK message to SSE events.

    Returns (events, text_was_emitted, emitted_tool_ids, thinking_emitted).
    """
    events: list[dict[str, Any]] = []
    tools = emitted_tool_ids if emitted_tool_ids is not None else set()
    thinking_emitted = emitted_thinking

    if isinstance(message, UserMessage):
        content = message.content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, ToolResultBlock):
                    events.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.tool_use_id,
                            "content": _format_tool_result(block.content),
                            "is_error": bool(block.is_error),
                        }
                    )
        return events, False, tools, thinking_emitted

    if isinstance(message, AssistantMessage):
        text_emitted = False
        for block in message.content:
            if isinstance(block, TextBlock) and not skip_text:
                events.append({"type": "text_delta", "content": block.text})
                text_emitted = True
            elif isinstance(block, ThinkingBlock) and not thinking_emitted:
                events.append({"type": "thinking", "content": block.thinking})
                thinking_emitted = True
            elif isinstance(block, ToolUseBlock):
                if block.id not in tools:
                    tools.add(block.id)
                    events.append(
                        {
                            "type": "tool_use",
                            "tool": block.name,
                            "tool_use_id": block.id,
                            "input": block.input if isinstance(block.input, dict) else {},
                        }
                    )
        return events, text_emitted, tools, thinking_emitted

    return events, False, tools, thinking_emitted


def _tool_use_event(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "tool": block.get("name", "unknown"),
        "tool_use_id": block.get("id", ""),
        "input": block.get("input") if isinstance(block.get("input"), dict) else {},
    }


def _format_tool_result(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        text = content
    else:
        try:
            text = json.dumps(content, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            text = str(content)
    if len(text) > _TOOL_RESULT_SSE_MAX:
        return text[:_TOOL_RESULT_SSE_MAX] + "\n…(truncated)"
    return text

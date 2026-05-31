"""Tests for SSE event mapping."""

from __future__ import annotations

from claude_agent_sdk.types import (
    AssistantMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from odk_platform.runtime.sse_mapper import message_to_sse, stream_event_to_sse


def test_stream_text_delta():
    events = stream_event_to_sse(
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "你好"},
        }
    )
    assert events == [{"type": "text_delta", "content": "你好"}]


def test_stream_tool_use_start():
    events = stream_event_to_sse(
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "Skill",
                "input": {},
            },
        }
    )
    assert len(events) == 1
    assert events[0]["type"] == "tool_use"
    assert events[0]["tool"] == "Skill"


def test_user_tool_result():
    msg = UserMessage(
        content=[
            ToolResultBlock(tool_use_id="toolu_1", content='{"rows": 1}', is_error=False)
        ]
    )
    events, _, tools, _ = message_to_sse(msg)
    assert events[0]["type"] == "tool_result"
    assert events[0]["tool_use_id"] == "toolu_1"


def test_assistant_skip_duplicate_text():
    msg = AssistantMessage(content=[TextBlock(text="full")], model="x")
    events, emitted, _, _ = message_to_sse(msg, skip_text=True)
    assert emitted is False
    assert not any(e["type"] == "text_delta" for e in events)


def test_assistant_thinking_and_tool():
    msg = AssistantMessage(
        content=[
            ThinkingBlock(thinking="plan", signature="sig"),
            ToolUseBlock(id="t1", name="mcp__postgres__run_query", input={"query": "SELECT 1"}),
            TextBlock(text="done"),
        ],
        model="x",
    )
    events, _, tools, thinking = message_to_sse(msg)
    types = [e["type"] for e in events]
    assert "thinking" in types
    assert "tool_use" in types
    assert "text_delta" in types
    assert thinking is True
    assert "t1" in tools

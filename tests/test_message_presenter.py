"""Tests for chronological message presentation."""

from __future__ import annotations

from odk_platform.runtime.message_presenter import present_messages


def test_turn_segments_interleaved_order():
    payloads = [
        {"type": "user", "content": "hello"},
        {
            "type": "assistant",
            "content": [
                {"type": "thinking", "thinking": "plan"},
                {"type": "tool_use", "id": "t1", "name": "mcp__postgres__run_query", "input": {}},
            ],
        },
        {
            "type": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "rows",
                    "is_error": False,
                }
            ],
        },
        {
            "type": "assistant",
            "content": [{"type": "text", "text": "结论第一段"}],
        },
        {
            "type": "assistant",
            "content": [
                {"type": "tool_use", "id": "t2", "name": "mcp__postgres__run_query", "input": {}},
            ],
        },
        {
            "type": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t2",
                    "content": "more",
                    "is_error": False,
                }
            ],
        },
        {
            "type": "assistant",
            "content": [{"type": "text", "text": "结论第二段"}],
        },
    ]
    out = present_messages(payloads)
    assert out[0]["role"] == "user"
    segs = out[1]["segments"]
    kinds = [s["kind"] for s in segs]
    assert kinds == [
        "thinking",
        "tool_use",
        "text",
        "tool_use",
        "text",
    ]
    assert segs[1].get("result") == "rows"
    assert segs[3].get("result") == "more"

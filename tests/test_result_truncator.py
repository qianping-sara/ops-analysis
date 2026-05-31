"""Tests for PostToolUse result truncator hook."""

from __future__ import annotations

import json

import pytest

from odk_platform.hooks.result_truncator import truncate_tool_result


@pytest.mark.asyncio
async def test_list_shaped_tool_response():
    """MCP may pass tool_response as content block list — must not call .get on list."""
    big = {"rows": [{"payload": "x" * 200} for i in range(400)], "row_count": 400}
    tool_response = [{"type": "text", "text": json.dumps(big)}]
    out = await truncate_tool_result(
        {
            "tool_name": "mcp__postgres__run_query",
            "tool_response": tool_response,
        },
        None,
        None,
    )
    assert "hookSpecificOutput" in out
    assert "updatedMCPToolOutput" in out["hookSpecificOutput"]


@pytest.mark.asyncio
async def test_dict_shaped_tool_response():
    big = {"rows": [{"payload": "x" * 200} for i in range(400)], "row_count": 400}
    out = await truncate_tool_result(
        {
            "tool_name": "mcp__postgres__run_query",
            "tool_response": big,
        },
        None,
        None,
    )
    assert out.get("hookSpecificOutput", {}).get("updatedMCPToolOutput")

"""PostToolUse result truncator for LLM observation."""

from __future__ import annotations

import json
from typing import Any

MAX_OBSERVATION_BYTES = 50_000


async def truncate_tool_result(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    tool_name = input_data.get("tool_name", "")
    if tool_name != "mcp__postgres__run_query":
        return {}

    tool_response = input_data.get("tool_response") or {}
    content = tool_response.get("content") or []
    if not content:
        return {}

    text = content[0].get("text", "") if isinstance(content[0], dict) else str(content[0])
    if len(text.encode("utf-8")) <= MAX_OBSERVATION_BYTES:
        return {}

    try:
        data = json.loads(text)
        rows = data.get("rows", [])
        summary = {
            "row_count": data.get("row_count", len(rows)),
            "truncated": True,
            "sample_rows": rows[:5],
            "note": "Full result stored in platform DB; observation truncated for context",
        }
        new_text = json.dumps(summary, ensure_ascii=False, default=str)
    except json.JSONDecodeError:
        new_text = text[:MAX_OBSERVATION_BYTES] + "…[truncated]"

    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolResponse": {
                "content": [{"type": "text", "text": new_text}],
            },
        }
    }

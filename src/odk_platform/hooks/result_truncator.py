"""PostToolUse result truncator for LLM observation."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_OBSERVATION_BYTES = 50_000


def _text_from_content_blocks(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, dict):
            parts.append(json.dumps(block, ensure_ascii=False, default=str))
        else:
            parts.append(str(block))
    return "\n".join(parts)


def _extract_response_text(tool_response: Any) -> str:
    """Normalize MCP / CLI tool_response shapes to a single text blob."""
    if tool_response is None:
        return ""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, list):
        return _text_from_content_blocks(tool_response)
    if isinstance(tool_response, dict):
        if "content" in tool_response:
            return _text_from_content_blocks(tool_response.get("content"))
        return json.dumps(tool_response, ensure_ascii=False, default=str)
    return str(tool_response)


def _wrap_truncated_output(original: Any, new_text: str) -> Any:
    """Preserve the tool_response shape the CLI expects."""
    if isinstance(original, list):
        return [{"type": "text", "text": new_text}]
    if isinstance(original, dict) and "content" in original:
        return {
            **original,
            "content": [{"type": "text", "text": new_text}],
        }
    if isinstance(original, dict):
        try:
            return json.loads(new_text)
        except json.JSONDecodeError:
            return {"text": new_text, "truncated": True}
    return [{"type": "text", "text": new_text}]


async def truncate_tool_result(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    try:
        if not isinstance(input_data, dict):
            logger.warning("truncate_tool_result: unexpected input_data type %s", type(input_data))
            return {}

        tool_name = input_data.get("tool_name", "")
        if tool_name != "mcp__postgres__run_query":
            return {}

        tool_response = input_data.get("tool_response")
        text = _extract_response_text(tool_response)
        if not text or len(text.encode("utf-8")) <= MAX_OBSERVATION_BYTES:
            return {}

        try:
            data = json.loads(text)
            rows = data.get("rows", []) if isinstance(data, dict) else []
            summary = {
                "row_count": data.get("row_count", len(rows)) if isinstance(data, dict) else len(rows),
                "truncated": True,
                "sample_rows": rows[:5] if isinstance(rows, list) else [],
                "note": "Full result stored in platform DB; observation truncated for context",
            }
            new_text = json.dumps(summary, ensure_ascii=False, default=str)
        except json.JSONDecodeError:
            new_text = text[:MAX_OBSERVATION_BYTES] + "…[truncated]"

        updated = _wrap_truncated_output(tool_response, new_text)
        return {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "updatedMCPToolOutput": updated,
            }
        }
    except Exception as exc:
        logger.exception("truncate_tool_result failed: %s", exc)
        return {}

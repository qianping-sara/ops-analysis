"""PreToolUse SQL validator hook."""

from __future__ import annotations

from typing import Any

from odk_platform.config import get_settings
from odk_platform.guardrails.sql_rules import validate_sql


async def validate_sql_before_execute(
    input_data: dict[str, Any],
    tool_use_id: str | None,
    context: Any,
) -> dict[str, Any]:
    tool_name = input_data.get("tool_name", "")
    if tool_name != "mcp__postgres__run_query":
        return {}

    tool_input = input_data.get("tool_input") or {}
    query = tool_input.get("query", "")
    settings = get_settings()
    result = validate_sql(query, max_rows=settings.sql_max_rows)

    if not result.ok:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": result.reason,
            }
        }

    if result.normalized_sql != query:
        tool_input["query"] = result.normalized_sql
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": tool_input,
            }
        }

    return {}

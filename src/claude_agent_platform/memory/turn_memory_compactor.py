"""Compact one turn's SDK payloads into a memory frame."""

from __future__ import annotations

import json
from typing import Any

from claude_agent_platform.memory.projectors.registry import MemoryProjectorRegistry

ASSISTANT_TEXT_CAP = 2048


def compact_turn(
    turn_payloads: list[dict[str, Any]],
    registry: MemoryProjectorRegistry,
    *,
    turn_index: int,
) -> dict[str, Any]:
    user_text = ""
    assistant_final = ""
    tools: list[dict[str, Any]] = []

    pending_tool: dict[str, Any] | None = None

    for payload in turn_payloads:
        ptype = payload.get("type") or payload.get("subtype") or ""
        content = payload.get("content") or []

        if ptype in ("user", "UserMessage") and isinstance(content, str):
            user_text = content
        elif ptype in ("user", "UserMessage") and isinstance(content, list):
            # tool results only — skip user capture
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result" and pending_tool:
                    proj = registry.get(pending_tool["tool"])
                    mem = proj.project_tool_result(
                        pending_tool["tool"],
                        pending_tool.get("input", {}),
                        block.get("content", ""),
                    )
                    tools.append({"tool": pending_tool["tool"], "memory": mem})
                    pending_tool = None
        elif ptype in ("assistant", "AssistantMessage"):
            texts = []
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif isinstance(block, dict) and block.get("type") == "tool_use":
                    pending_tool = {
                        "tool": block.get("name", ""),
                        "input": block.get("input", {}),
                    }
                    proj = registry.get(block.get("name", ""))
                    tools.append(
                        {
                            "tool": block.get("name", ""),
                            "memory": proj.project_tool_use(
                                block.get("name", ""), block.get("input", {})
                            ),
                        }
                    )
            if texts:
                assistant_final = "\n".join(texts)[-ASSISTANT_TEXT_CAP:]

    return {
        "turn_index": turn_index,
        "user": user_text,
        "assistant_final": assistant_final,
        "tools": tools,
    }

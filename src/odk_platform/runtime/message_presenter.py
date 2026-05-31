"""Present SDK payloads for frontend API."""

from __future__ import annotations

from typing import Any


def present_messages(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project stored payloads to UI-friendly message list."""
    out: list[dict[str, Any]] = []
    for p in payloads:
        ptype = p.get("type", "")
        if ptype == "user":
            content = p.get("content")
            if isinstance(content, str) and content.strip():
                out.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # tool-only user message — fold
                if not _is_tool_only(content):
                    text = _extract_text(content)
                    if text:
                        out.append({"role": "user", "content": text})
                else:
                    out.append({"role": "system", "content": "已查询数据库", "collapsed": True})
        elif ptype == "assistant":
            text = _content_to_text(p.get("content"))
            tools = _extract_tools(p.get("content"))
            item: dict[str, Any] = {"role": "assistant", "content": text}
            if tools:
                item["tools"] = tools
            if text or tools:
                out.append(item)
        # skip result / system for UI
    return out


def _is_tool_only(content: list[Any]) -> bool:
    return all(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return _content_to_text(content)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts)


def _extract_tools(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    tools = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tools.append({"name": block.get("name"), "input": block.get("input")})
    return tools

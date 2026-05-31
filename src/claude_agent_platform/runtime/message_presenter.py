"""Present SDK payloads for frontend API."""

from __future__ import annotations

from typing import Any

from claude_agent_platform.runtime.sse_mapper import _format_tool_result


def present_messages(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project stored payloads to UI-friendly message list (chronological segments)."""
    out: list[dict[str, Any]] = []
    i = 0
    n = len(payloads)

    while i < n:
        p = payloads[i]
        ptype = p.get("type", "")

        if ptype == "user":
            content = p.get("content")
            if isinstance(content, str) and content.strip():
                out.append({"role": "user", "content": content})
                i += 1
                segments = _collect_turn_segments(payloads, i)
                i += _turn_payload_span(payloads, i)
                if segments:
                    out.append({"role": "assistant", "segments": segments})
                continue

            if isinstance(content, list) and _is_tool_only(content):
                i += 1
                continue

            if isinstance(content, list):
                text = _extract_text(content)
                if text:
                    out.append({"role": "user", "content": text})
            i += 1
            continue

        if ptype == "assistant":
            segments = _blocks_to_segments(p.get("content"))
            i += 1
            while i < n:
                p2 = payloads[i]
                if p2.get("type") == "user" and _is_tool_only(p2.get("content")):
                    for block in p2["content"]:
                        if block.get("type") == "tool_result":
                            _apply_tool_result(segments, block)
                    i += 1
                    continue
                if p2.get("type") == "assistant":
                    segments.extend(_blocks_to_segments(p2.get("content")))
                    i += 1
                    continue
                break
            if segments:
                out.append({"role": "assistant", "segments": segments})
            continue

        i += 1

    return out


def _turn_payload_span(payloads: list[dict[str, Any]], start: int) -> int:
    """How many payloads belong to the assistant turn following a user message."""
    span = 0
    i = start
    while i < len(payloads):
        p = payloads[i]
        ptype = p.get("type", "")
        if ptype == "user" and isinstance(p.get("content"), str) and str(p["content"]).strip():
            break
        if ptype in ("assistant", "user"):
            span += 1
            i += 1
            continue
        break
    return span


def _collect_turn_segments(payloads: list[dict[str, Any]], start: int) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    i = start
    end = start + _turn_payload_span(payloads, start)
    while i < end:
        p = payloads[i]
        if p.get("type") == "assistant":
            segments.extend(_blocks_to_segments(p.get("content")))
        elif p.get("type") == "user" and _is_tool_only(p.get("content")):
            for block in p["content"]:
                if block.get("type") == "tool_result":
                    _apply_tool_result(segments, block)
        i += 1
    return segments


def _blocks_to_segments(content: Any) -> list[dict[str, Any]]:
    """Preserve block order within one SDK assistant message."""
    segments: list[dict[str, Any]] = []
    if isinstance(content, str):
        if content.strip():
            segments.append({"kind": "text", "content": content})
        return segments
    if not isinstance(content, list):
        return segments

    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "thinking":
            segments.append({"kind": "thinking", "content": block.get("thinking", "")})
        elif btype == "tool_use":
            segments.append(_activity_tool_use(block))
        elif btype == "text":
            text = block.get("text", "")
            if text:
                segments.append({"kind": "text", "content": text})
    return segments


def _apply_tool_result(segments: list[dict[str, Any]], block: dict[str, Any]) -> None:
    tid = block.get("tool_use_id", "")
    for seg in reversed(segments):
        if seg.get("kind") == "tool_use" and seg.get("tool_use_id") == tid:
            seg["result"] = _format_tool_result(block.get("content"))
            seg["is_error"] = bool(block.get("is_error"))
            return
    segments.append(_activity_tool_result(block))


def _activity_tool_use(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "tool_use",
        "tool": block.get("name", "unknown"),
        "tool_use_id": block.get("id", ""),
        "input": block.get("input") if isinstance(block.get("input"), dict) else {},
    }


def _activity_tool_result(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "tool_result",
        "tool_use_id": block.get("tool_use_id", ""),
        "content": _format_tool_result(block.get("content")),
        "is_error": bool(block.get("is_error")),
    }


def _is_tool_only(content: Any) -> bool:
    return isinstance(content, list) and all(
        isinstance(c, dict) and c.get("type") == "tool_result" for c in content
    )


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

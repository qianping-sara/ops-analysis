"""Render memory frames to cold-resume prefix text."""

from __future__ import annotations

from typing import Any


def _estimate_tokens(text: str) -> int:
    # Rough heuristic: ~4 chars per token for mixed CN/EN
    return max(1, len(text) // 4)


def build_cold_prefix(
    frames: list[dict[str, Any]],
    *,
    max_tokens: int,
) -> str:
    if not frames:
        return ""

    selected = list(frames)
    while selected:
        text = _render_frames(selected)
        if _estimate_tokens(text) <= max_tokens:
            return text
        selected = selected[1:]

    # Last resort: most recent frame only, assistant truncated
    if frames:
        f = dict(frames[-1])
        f["assistant_final"] = (f.get("assistant_final") or "")[:512]
        f["tools"] = f.get("tools", [])[:2]
        return _render_frames([f])
    return ""


def _render_frames(frames: list[dict[str, Any]]) -> str:
    lines = ["【会话续接 - 此前轮次】"]
    for i, frame in enumerate(frames, start=1):
        lines.append(f"Turn {frame.get('turn_index', i)}")
        lines.append(f"  用户: {frame.get('user', '')}")
        for t in frame.get("tools", []):
            mem = t.get("memory", {})
            lines.append(f"  工具: {t.get('tool')} → {mem}")
        assistant = frame.get("assistant_final", "")
        if assistant:
            lines.append(f"  助手: {assistant[:500]}")
    return "\n".join(lines)

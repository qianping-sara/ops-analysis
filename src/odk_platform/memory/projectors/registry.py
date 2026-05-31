"""Memory projectors for turn compaction."""

from __future__ import annotations

import json
from typing import Any, Protocol


class MemoryProjector(Protocol):
    def project_tool_use(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]: ...
    def project_tool_result(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> dict[str, Any]: ...


class DefaultToolMemoryProjector:
    def project_tool_use(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        return {"tool": tool_name, "input_preview": str(tool_input)[:200]}

    def project_tool_result(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> dict[str, Any]:
        return {"tool": tool_name, "output_preview": tool_output[:200]}


class PostgresQueryMemoryProjector:
    def project_tool_use(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        sql = tool_input.get("query", "")
        return {"tool": tool_name, "intent": sql[:120]}

    def project_tool_result(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str | list | dict
    ) -> dict[str, Any]:
        try:
            data = _coerce_tool_output(tool_output)
            return {
                "tool": tool_name,
                "row_count": data.get("row_count"),
                "truncated": data.get("truncated", False),
            }
        except (json.JSONDecodeError, TypeError):
            return {"tool": tool_name, "note": str(tool_output)[:120]}


def _coerce_tool_output(tool_output: str | list | dict) -> dict[str, Any]:
    if isinstance(tool_output, dict):
        return tool_output
    if isinstance(tool_output, list):
        return {"rows": tool_output, "row_count": len(tool_output)}
    if isinstance(tool_output, str):
        parsed = json.loads(tool_output)
        return parsed if isinstance(parsed, dict) else {"raw": parsed}
    return {"raw": str(tool_output)}


class PostgresMetaMemoryProjector:
    def project_tool_use(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        return {"tool": tool_name}

    def project_tool_result(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> dict[str, Any]:
        name = tool_input.get("name", "")
        if "list_tables" in tool_name:
            return {"tool": tool_name, "note": "已列出表"}
        return {"tool": tool_name, "note": f"已查看表 {name} 结构"}


class SkillMemoryProjector:
    def project_tool_use(self, tool_name: str, tool_input: dict[str, Any]) -> dict[str, Any]:
        skill = tool_input.get("skill", tool_input.get("name", "unknown"))
        return {"tool": tool_name, "note": f"已加载 Skill: {skill}"}

    def project_tool_result(
        self, tool_name: str, tool_input: dict[str, Any], tool_output: str
    ) -> dict[str, Any]:
        return {"tool": tool_name, "note": "Skill 已加载"}


class MemoryProjectorRegistry:
    def __init__(self) -> None:
        self._projectors: dict[str, MemoryProjector] = {}
        self._default = DefaultToolMemoryProjector()

    def register(self, tool_name: str, projector: MemoryProjector) -> None:
        self._projectors[tool_name] = projector

    def get(self, tool_name: str) -> MemoryProjector:
        if tool_name in self._projectors:
            return self._projectors[tool_name]
        if tool_name.startswith("mcp__postgres__"):
            if "run_query" in tool_name:
                return self._projectors.get("mcp__postgres__run_query", self._default)
            return self._projectors.get("mcp__postgres__describe_table", self._default)
        if tool_name == "Skill":
            return self._projectors.get("Skill", self._default)
        return self._default


def build_default_registry() -> MemoryProjectorRegistry:
    reg = MemoryProjectorRegistry()
    reg.register("mcp__postgres__run_query", PostgresQueryMemoryProjector())
    reg.register("mcp__postgres__describe_table", PostgresMetaMemoryProjector())
    reg.register("mcp__postgres__list_tables", PostgresMetaMemoryProjector())
    reg.register("Skill", SkillMemoryProjector())
    return reg

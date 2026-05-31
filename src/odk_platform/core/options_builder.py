"""Build ClaudeAgentOptions from AgentProfile."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

from odk_platform.config import get_settings
from odk_platform.core.profile import AgentProfile
from odk_platform.hooks.result_truncator import truncate_tool_result
from odk_platform.hooks.sql_validator import validate_sql_before_execute
from odk_platform.mcp.postgres_server import build_postgres_mcp_config


def build_system_prompt(profile: AgentProfile) -> str:
    agent_dir = profile.agent_dir
    system_path = agent_dir / "system_prompt.md"
    parts = [system_path.read_text(encoding="utf-8")]

    if profile.prompt_caching.static_prefix.get("inline_skill_references"):
        refs_dir = agent_dir / profile.skills_dir / "topic-daily-analysis" / "references"
        if refs_dir.is_dir():
            parts.append("\n\n---\n## Skill References (inline)\n")
            for ref in sorted(refs_dir.glob("*.md")):
                parts.append(f"\n### {ref.name}\n")
                parts.append(ref.read_text(encoding="utf-8"))

    return "\n".join(parts)


def build_options(
    profile: AgentProfile,
    *,
    resume: str | None = None,
    cold_prefix: str | None = None,
) -> ClaudeAgentOptions:
    settings = get_settings()
    system = build_system_prompt(profile)
    agent_dir = str(profile.agent_dir.resolve())

    hooks: dict[str, list[HookMatcher]] = {}
    custom_hooks = profile.hooks.get("custom", [])
    if "sql_validator" in custom_hooks:
        hooks.setdefault("PreToolUse", []).append(
            HookMatcher(matcher="mcp__postgres__run_query", hooks=[validate_sql_before_execute])
        )
    if "result_truncator" in custom_hooks:
        hooks.setdefault("PostToolUse", []).append(
            HookMatcher(matcher="mcp__postgres__run_query", hooks=[truncate_tool_result])
        )

    mcp_servers = {}
    if "postgres" in profile.mcp_servers:
        mcp_servers.update(build_postgres_mcp_config())

    opts = ClaudeAgentOptions(
        system_prompt=system,
        model=profile.model,
        max_turns=profile.max_turns,
        cwd=agent_dir,
        allowed_tools=profile.allowed_tools,
        setting_sources=profile.setting_sources,
        skills=["topic-daily-analysis"],
        mcp_servers=mcp_servers,
        hooks=hooks,
        permission_mode="acceptEdits",
        include_partial_messages=True,
    )

    if resume and not cold_prefix:
        opts = replace(opts, resume=resume)

    return opts


def wrap_user_message(text: str, cold_prefix: str | None) -> str:
    if not cold_prefix:
        return text
    return f"{cold_prefix}\n\n【当前消息】\n{text}"

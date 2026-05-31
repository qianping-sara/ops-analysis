"""Agent Profile models and YAML loading."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class SqlGuardrailsConfig(BaseModel):
    max_rows: int = 10000
    statement_timeout_ms: int = 30000


class MemoryConfig(BaseModel):
    enabled: bool = True
    ttl_hours: int = 24
    working_set_turns: int = 20
    cold_resume_max_turns: int = 10
    cold_resume_max_tokens: int = 32000
    projectors: list[str] = Field(default_factory=list)


class PromptCachingConfig(BaseModel):
    enabled: bool = True
    mode: Literal["automatic", "explicit", "off"] = "automatic"
    ttl: str = "5m"
    static_prefix: dict[str, Any] = Field(default_factory=dict)


class AgentProfile(BaseModel):
    id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    model: str = "claude-sonnet-4-6"
    max_turns: int = 20
    invocation_modes: list[str] = Field(default_factory=lambda: ["api"])
    delegates: list[str] = Field(default_factory=list)
    skills_dir: str = "skills"
    setting_sources: list[str] = Field(default_factory=lambda: ["project"])
    mcp_servers: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    hooks: dict[str, Any] = Field(default_factory=dict)
    guardrails: dict[str, Any] = Field(default_factory=dict)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    prompt_caching: PromptCachingConfig = Field(default_factory=PromptCachingConfig)

    @property
    def agent_dir(self) -> Path:
        return Path(self._agent_dir)  # type: ignore[attr-defined]

    @property
    def sql_guardrails(self) -> SqlGuardrailsConfig:
        raw = self.guardrails.get("sql", {})
        return SqlGuardrailsConfig(**raw) if raw else SqlGuardrailsConfig()


_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _resolve_env(value: str) -> str:
    def repl(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), match.group(0))

    return _ENV_PATTERN.sub(repl, value)


def _resolve_env_deep(obj: Any) -> Any:
    if isinstance(obj, str):
        return _resolve_env(obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_deep(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_deep(v) for v in obj]
    return obj


def load_profile(path: Path) -> AgentProfile:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw = _resolve_env_deep(raw)
    profile = AgentProfile(**raw)
    profile._agent_dir = str(path.parent)  # type: ignore[attr-defined]
    return profile

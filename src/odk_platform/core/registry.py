"""Agent Registry — scan agents/*/profile.yaml."""

from __future__ import annotations

from pathlib import Path

from odk_platform.core.profile import AgentProfile, load_profile


class AgentRegistry:
    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}

    def register(self, profile: AgentProfile) -> None:
        self._profiles[profile.id] = profile

    def get(self, agent_id: str) -> AgentProfile:
        if agent_id not in self._profiles:
            raise KeyError(f"Unknown agent: {agent_id}")
        return self._profiles[agent_id]

    def list_agents(self) -> list[AgentProfile]:
        return list(self._profiles.values())

    def load_from_directory(self, agents_dir: Path) -> None:
        if not agents_dir.is_dir():
            raise FileNotFoundError(f"Agents directory not found: {agents_dir}")
        for profile_path in sorted(agents_dir.glob("*/profile.yaml")):
            profile = load_profile(profile_path)
            self.register(profile)


_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    global _registry
    if _registry is None:
        raise RuntimeError("Agent registry not initialized")
    return _registry


def init_registry(agents_dir: Path) -> AgentRegistry:
    global _registry
    _registry = AgentRegistry()
    _registry.load_from_directory(agents_dir)
    return _registry

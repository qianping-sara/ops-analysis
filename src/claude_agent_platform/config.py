"""Application configuration from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Azure Foundry (Claude)
    claude_azure_api_key: str = Field(alias="CLAUDE_AZURE_API_KEY")
    claude_azure_foundry_endpoint: str = Field(alias="CLAUDE_AZURE_FOUNDRY_ENDPOINT")
    claude_azure_foundry_model: str = Field(
        default="claude-sonnet-4-6",
        alias="CLAUDE_AZURE_FOUNDRY_MODEL",
    )

    # Dual DB — must not be confused
    postgres_url: str = Field(alias="POSTGRES_URL")
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    sql_max_rows: int = Field(default=10000, alias="SQL_MAX_ROWS")
    sql_statement_timeout_ms: int = Field(default=30000, alias="SQL_STATEMENT_TIMEOUT_MS")
    sql_max_result_bytes: int = Field(default=2_097_152, alias="SQL_MAX_RESULT_BYTES")

    prompt_caching_enabled: bool = Field(default=True, alias="PROMPT_CACHING_ENABLED")

    # Paths
    project_root: str = Field(default_factory=lambda: _default_project_root())
    agents_dir: str = Field(default="agents")

    # Runtime
    client_idle_seconds: int = Field(default=900, alias="CLIENT_IDLE_SECONDS")
    dev_user_email: str = Field(default="dev@claude-agent.local", alias="DEV_USER_EMAIL")

    @model_validator(mode="after")
    def validate_dual_db(self) -> Settings:
        pg = urlparse(self.postgres_url)
        plat = urlparse(self.database_url)
        if pg.geturl() == plat.geturl():
            raise ValueError(
                "POSTGRES_URL and DATABASE_URL must differ (business vs platform DB)"
            )
        if pg.hostname and plat.hostname and pg.hostname == plat.hostname and pg.path == plat.path:
            raise ValueError(
                "POSTGRES_URL and DATABASE_URL appear to point at the same database"
            )
        return self

    def apply_foundry_env(self) -> None:
        """Map settings to Claude Agent SDK / Foundry env vars."""
        base = self.claude_azure_foundry_endpoint.rstrip("/")
        if base.endswith("/v1/messages"):
            base = base[: -len("/v1/messages")]
        if not base.endswith("/anthropic"):
            # Accept resource root URL as well
            base = base.rstrip("/") + ("/anthropic" if "/anthropic" not in base else "")

        os.environ["CLAUDE_CODE_USE_FOUNDRY"] = "1"
        os.environ["ANTHROPIC_FOUNDRY_API_KEY"] = self.claude_azure_api_key
        os.environ["ANTHROPIC_FOUNDRY_BASE_URL"] = base
        os.environ["ANTHROPIC_DEFAULT_SONNET_MODEL"] = self.claude_azure_foundry_model
        os.environ["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = self.claude_azure_foundry_model
        os.environ["ANTHROPIC_DEFAULT_OPUS_MODEL"] = self.claude_azure_foundry_model
        os.environ["ANTHROPIC_MODEL"] = self.claude_azure_foundry_model


def _default_project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@lru_cache
def get_settings() -> Settings:
    return Settings()

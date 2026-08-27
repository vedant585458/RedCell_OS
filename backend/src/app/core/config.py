"""Global configuration and environment settings for RedCell_OS with pydantic-settings."""

import os
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """Raised when configuration validation fails during startup."""

    pass


class Settings(BaseSettings):
    """Central configuration schema for RedCell_OS backend and multi-agent orchestrator."""

    model_config = SettingsConfigDict(
        env_prefix="REDCELL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General App Information
    app_name: str = Field(default="RedCell_OS", description="Application system name")
    version: str = Field(default="0.1.0", description="Application release version")
    environment: Literal["development", "staging", "production", "test"] = Field(
        default="development", description="Running environment stage"
    )

    # Server Networking
    host: str = Field(default="0.0.0.0", description="Host interface to bind")
    port: int = Field(default=8000, ge=1, le=65535, description="Port number to listen on")
    cors_origins: list[str] = Field(default=["*"], description="Allowed CORS origins")

    # Logging & Observability
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", description="Log verbosity level"
    )
    json_logs: bool = Field(
        default=False, description="Format logs as structured JSON for machine ingestion"
    )

    # Storage & Persistence
    data_dir: str = Field(
        default="./data",
        description="Root directory for local SQLite databases, workspaces, and artifacts",
    )

    # LLM Provider & Reasoning Engine (ADR-006)
    llm_provider: Literal["mock", "anthropic", "openai", "ollama"] = Field(
        default="mock", description="Active LLM provider backend"
    )
    llm_model: str = Field(default="mock-deterministic-v1", description="Model name identifier")
    openai_api_key: str | None = Field(default=None, description="OpenAI API secret key")
    anthropic_api_key: str | None = Field(default=None, description="Anthropic API secret key")
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434", description="Base URL for local Ollama / vLLM endpoint"
    )
    llm_temperature: float = Field(default=0.2, ge=0.0, le=1.0, description="Sampling temperature")
    llm_timeout_sec: float = Field(
        default=45.0, ge=5.0, le=300.0, description="Per-call LLM timeout"
    )

    # Subprocess Sandboxing & Quotas (ADR-005)
    sandbox_mode: Literal["subprocess", "docker"] = Field(
        default="subprocess", description="Agent execution isolation mechanism"
    )
    sandbox_ram_mb: int = Field(
        default=1024, ge=128, le=16384, description="Max RAM quota per agent process"
    )
    sandbox_cpu_sec: int = Field(
        default=60, ge=5, le=3600, description="Max CPU time allowance per command"
    )
    sandbox_timeout_sec: float = Field(
        default=120.0, ge=5.0, le=3600.0, description="Wall-clock execution timeout"
    )

    @field_validator("port")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ConfigurationError(f"Invalid server port '{v}'. Must be between 1 and 65535.")
        return v

    def validate_startup(self) -> None:
        """Perform fail-fast startup assertions for required filesystem directories and credentials."""
        # Validate data directory writeability
        try:
            resolved_data_dir = os.path.abspath(self.data_dir)
            os.makedirs(resolved_data_dir, exist_ok=True)
            test_file = os.path.join(resolved_data_dir, ".write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except Exception as err:
            raise ConfigurationError(
                f"Data directory '{self.data_dir}' is not writable or cannot be created: {err}"
            ) from err

        # Validate cloud LLM provider credentials when active in non-mock mode
        if self.llm_provider == "openai" and not self.openai_api_key:
            raise ConfigurationError(
                "REDCELL_LLM_PROVIDER is set to 'openai' but REDCELL_OPENAI_API_KEY is not configured."
            )
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ConfigurationError(
                "REDCELL_LLM_PROVIDER is set to 'anthropic' but REDCELL_ANTHROPIC_API_KEY is not configured."
            )

    def safe_dict(self) -> dict[str, Any]:
        """Return a dictionary of configuration settings with sensitive secrets securely masked."""
        data = self.model_dump()
        sensitive_keys = {"openai_api_key", "anthropic_api_key"}

        for key in sensitive_keys:
            if data.get(key):
                val = str(data[key])
                if len(val) > 8:
                    data[key] = f"{val[:4]}...{val[-4:]}"
                else:
                    data[key] = "********"

        return data


def get_settings() -> Settings:
    """Instantiate settings with fail-fast validation."""
    s = Settings()
    s.validate_startup()
    return s


# Global singleton settings instance
settings = get_settings()

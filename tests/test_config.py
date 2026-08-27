"""Unit tests for the backend Settings and configuration validation."""

import pytest
from app.config import ConfigurationError, Settings
from pydantic import ValidationError


def test_default_settings_validity():
    s = Settings()
    s.validate_startup()

    assert s.app_name == "RedCell_OS"
    assert s.port == 8000
    assert s.host == "0.0.0.0"
    assert s.llm_provider == "mock"
    assert s.sandbox_mode == "subprocess"
    assert s.sandbox_ram_mb == 1024


def test_environment_variable_override(monkeypatch):
    monkeypatch.setenv("REDCELL_PORT", "9090")
    monkeypatch.setenv("REDCELL_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("REDCELL_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("REDCELL_SANDBOX_RAM_MB", "2048")

    s = Settings()
    assert s.port == 9090
    assert s.log_level == "DEBUG"
    assert s.llm_provider == "ollama"
    assert s.sandbox_ram_mb == 2048


def test_invalid_port_validation():
    with pytest.raises(ValidationError):
        Settings(port=70000)

    with pytest.raises(ValidationError):
        Settings(port=0)


def test_openai_missing_key_fail_fast():
    s = Settings(llm_provider="openai", openai_api_key=None)
    with pytest.raises(ConfigurationError) as exc_info:
        s.validate_startup()

    assert "REDCELL_OPENAI_API_KEY is not configured" in str(exc_info.value)


def test_anthropic_missing_key_fail_fast():
    s = Settings(llm_provider="anthropic", anthropic_api_key=None)
    with pytest.raises(ConfigurationError) as exc_info:
        s.validate_startup()

    assert "REDCELL_ANTHROPIC_API_KEY is not configured" in str(exc_info.value)


def test_safe_dict_masks_secrets():
    s = Settings(
        openai_api_key="sk-proj-secret-1234567890-test-key",
        anthropic_api_key="sk-ant-secret-abcdef-123456",
    )
    safe = s.safe_dict()

    assert "sk-proj-secret-1234567890-test-key" not in str(safe)
    assert "sk-ant-secret-abcdef-123456" not in str(safe)
    assert "..." in safe["openai_api_key"]
    assert "..." in safe["anthropic_api_key"]

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentic_data_analyst.config import Settings


def test_settings_are_typed_and_secret_is_redacted() -> None:
    settings = Settings.from_env(
        {
            "OPENROUTER_API_KEY": "sensitive-key",
            "MAX_RESULT_ROWS": "25",
            "LLM_TIMEOUT_SECONDS": "12.5",
            "MAX_LLM_RESPONSE_BYTES": "2048",
        }
    )

    assert settings.max_result_rows == 25
    assert settings.llm_timeout_seconds == 12.5
    assert settings.analysis_policy.max_result_rows == 25
    assert "sensitive-key" not in repr(settings)


def test_settings_load_dotenv_without_mutating_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENROUTER_API_KEY=file-secret\nMAX_RESULT_ROWS=25\nLLM_TIMEOUT_SECONDS=12.5\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("MAX_RESULT_ROWS", raising=False)
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)

    settings = Settings.from_env(env_file=env_file)

    assert settings.openrouter_api_key is not None
    assert settings.openrouter_api_key.get_secret_value() == "file-secret"
    assert settings.max_result_rows == 25
    assert settings.llm_timeout_seconds == 12.5
    assert "OPENROUTER_API_KEY" not in os.environ


def test_process_environment_overrides_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENROUTER_API_KEY=file-secret\nMAX_RESULT_ROWS=25\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "process-secret")
    monkeypatch.setenv("MAX_RESULT_ROWS", "50")

    settings = Settings.from_env(env_file=env_file)

    assert settings.openrouter_api_key is not None
    assert settings.openrouter_api_key.get_secret_value() == "process-secret"
    assert settings.max_result_rows == 50


def test_explicit_environment_does_not_read_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MAX_RESULT_ROWS=25\n", encoding="utf-8")

    settings = Settings.from_env({"MAX_RESULT_ROWS": "50"}, env_file=env_file)

    assert settings.max_result_rows == 50


@pytest.mark.parametrize(
    "environment",
    [
        {"MAX_RESULT_ROWS": "0"},
        {"MAX_RESULT_ROWS": "not-an-integer"},
        {"LLM_TIMEOUT_SECONDS": "0"},
        {"MAX_LLM_RESPONSE_BYTES": "100"},
        {"OPENROUTER_BASE_URL": "not-a-url"},
        {"SPARK_MASTER": ""},
    ],
)
def test_invalid_settings_fail_during_startup_validation(environment: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Settings.from_env(environment)

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

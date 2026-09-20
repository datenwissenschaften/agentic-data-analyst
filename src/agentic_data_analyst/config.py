"""Typed, environment-backed application configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from dotenv import dotenv_values
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, field_validator

from agentic_data_analyst.policy import MAX_RESULT_ROWS_HARD, AnalysisPolicy


class Settings(BaseModel):
    """Validated runtime settings loaded at the composition boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_path: Path = Path("data/sample")
    spark_master: str = Field(default="local[2]", min_length=1, max_length=200)
    max_result_rows: int = Field(default=100, gt=0, le=MAX_RESULT_ROWS_HARD)
    openrouter_api_key: SecretStr | None = None
    openrouter_model: str = Field(default="openai/gpt-4.1-mini", min_length=1, max_length=200)
    openrouter_base_url: AnyHttpUrl = AnyHttpUrl("https://openrouter.ai/api/v1")
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    llm_max_attempts: int = Field(default=2, ge=1, le=5)
    max_llm_response_bytes: int = Field(default=1_000_000, ge=1_024, le=10_000_000)
    execution_timeout_seconds: float | None = Field(default=120.0, gt=0, le=3_600)

    @field_validator("catalog_path")
    @classmethod
    def expand_catalog_path(cls, value: Path) -> Path:
        return value.expanduser()

    @property
    def analysis_policy(self) -> AnalysisPolicy:
        return AnalysisPolicy(max_result_rows=self.max_result_rows)

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        env_file: Path | None = Path(".env"),
    ) -> Settings:
        if environ is None:
            file_values = (
                {
                    key: value
                    for key, value in dotenv_values(env_file, encoding="utf-8").items()
                    if value is not None
                }
                if env_file is not None
                else {}
            )
            source: Mapping[str, str] = {**file_values, **os.environ}
        else:
            source = environ
        key = source.get("OPENROUTER_API_KEY")
        return cls.model_validate(
            {
                "catalog_path": source.get("DATA_CATALOG_PATH", "data/sample"),
                "spark_master": source.get("SPARK_MASTER", "local[2]"),
                "max_result_rows": source.get("MAX_RESULT_ROWS", "100"),
                "openrouter_api_key": key if key else None,
                "openrouter_model": source.get("OPENROUTER_MODEL", "openai/gpt-4.1-mini"),
                "openrouter_base_url": source.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                "llm_timeout_seconds": source.get("LLM_TIMEOUT_SECONDS", "60"),
                "llm_max_attempts": source.get("LLM_MAX_ATTEMPTS", "2"),
                "max_llm_response_bytes": source.get("MAX_LLM_RESPONSE_BYTES", "1000000"),
                "execution_timeout_seconds": source.get("EXECUTION_TIMEOUT_SECONDS", "120"),
            }
        )

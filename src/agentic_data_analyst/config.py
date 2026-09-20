"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings with side-effect-free environment loading."""

    catalog_path: Path = Path("data/sample")
    spark_master: str = "local[2]"
    max_result_rows: int = 100
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4.1-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> Settings:
        key = os.getenv("OPENROUTER_API_KEY")
        return cls(
            catalog_path=Path(os.getenv("DATA_CATALOG_PATH", "data/sample")),
            spark_master=os.getenv("SPARK_MASTER", "local[2]"),
            max_result_rows=int(os.getenv("MAX_RESULT_ROWS", "100")),
            openrouter_api_key=key if key else None,
            openrouter_model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini"),
            openrouter_base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/"),
            llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        )

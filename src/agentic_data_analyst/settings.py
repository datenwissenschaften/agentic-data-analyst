"""Runtime settings from the environment (`.env`), so model, effort, database and log level change without code edits.

Loaded here rather than in `app.py`, because other modules read these values when they are imported.
"""

import os
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

Effort = Literal["low", "medium", "high", "xhigh", "max"]
EFFORTS: tuple[Effort, ...] = ("low", "medium", "high", "xhigh", "max")

load_dotenv()


def _effort(value: str) -> Effort:
    for effort in EFFORTS:
        if effort == value:
            return effort
    raise ValueError(f"ANALYST_EFFORT must be one of {', '.join(EFFORTS)}, got {value!r}")


# Haiku 4.5 is the cheapest current model; switch to claude-sonnet-5-5 or claude-opus-5-5 for harder questions.
DEFAULT_MODEL = "claude-haiku-4-5"
MODEL = os.environ.get("ANALYST_MODEL", DEFAULT_MODEL)
# Ignored by Haiku 4.5, which has no effort setting (see request_options).
EFFORT = _effort(os.environ.get("ANALYST_EFFORT", "low"))
# The reviewer only judges one query at a time, so the cheapest model is enough.
REVIEWER_MODEL = os.environ.get("ANALYST_REVIEWER_MODEL", DEFAULT_MODEL)
REVIEWER_EFFORT = _effort(os.environ.get("ANALYST_REVIEWER_EFFORT", "low"))
# Hard spending limits in USD. An answer stops before the next model call once it has cost more than its budget; a
# chat stops taking questions once it has cost more than its budget. Unpriced models fail closed (see agent.py).
ANSWER_BUDGET_USD = float(os.environ.get("ANALYST_ANSWER_BUDGET_USD", "0.50"))
SESSION_BUDGET_USD = float(os.environ.get("ANALYST_SESSION_BUDGET_USD", "5.00"))
DATABASE_PATH = Path(os.environ.get("ANALYST_DATABASE", "data/speedruns.duckdb"))
# Any loguru level name; an unknown name fails at startup.
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


def request_options(model: str, effort: Effort) -> dict[str, Any]:
    """The request options a model accepts.

    Haiku 4.5 rejects `effort` and has no safety classifiers, so there is nothing for server-side fallbacks to do.
    The newer models take an effort level and, on a safety decline, re-run on Anthropic's recommended fallback model.
    """
    if model.startswith("claude-haiku-4-5"):
        return {}
    return {"output_config": {"effort": effort}, "betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

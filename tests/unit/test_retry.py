import asyncio

import pytest

from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.llm import FakeLLMClient, Message, complete_structured_with_retry
from agentic_data_analyst.models import DiscoverySelection


def test_retry_succeeds_on_first_attempt() -> None:
    llm = FakeLLMClient([{"datasets": ["sessions"], "rationale": "Sessions measure activity."}])

    result = asyncio.run(
        complete_structured_with_retry(
            llm,
            messages=[Message(role="user", content="find data")],
            response_model=DiscoverySelection,
            max_attempts=3,
        )
    )

    assert result.datasets == ("sessions",)
    assert len(llm.calls) == 1


def test_retry_recovers_after_schema_validation_failure() -> None:
    llm = FakeLLMClient(
        [
            {"datasets": ["sessions"], "rationale": "activity", "unexpected": "field"},
            {"datasets": ["sessions"], "rationale": "activity"},
        ]
    )

    result = asyncio.run(
        complete_structured_with_retry(
            llm,
            messages=[Message(role="user", content="find data")],
            response_model=DiscoverySelection,
            max_attempts=2,
        )
    )

    assert result.datasets == ("sessions",)
    assert len(llm.calls) == 2
    # The second attempt includes feedback about the first failure.
    assert "invalid" in llm.calls[1][0][-1].content


def test_retry_recovers_after_check_failure() -> None:
    llm = FakeLLMClient(
        [
            {"datasets": ["unknown_table"], "rationale": "wrong"},
            {"datasets": ["sessions"], "rationale": "activity"},
        ]
    )

    def check(response: DiscoverySelection) -> None:
        if "unknown_table" in response.datasets:
            raise LLMError("dataset not allowed")

    result = asyncio.run(
        complete_structured_with_retry(
            llm,
            messages=[Message(role="user", content="find data")],
            response_model=DiscoverySelection,
            check=check,
            max_attempts=2,
        )
    )

    assert result.datasets == ("sessions",)
    assert len(llm.calls) == 2


def test_retry_raises_last_error_when_exhausted() -> None:
    llm = FakeLLMClient(
        [
            {"datasets": ["sessions"], "rationale": "activity", "unexpected": "field"},
            {"datasets": ["sessions"], "rationale": "activity", "unexpected": "field"},
        ]
    )

    with pytest.raises(LLMError, match="failed validation"):
        asyncio.run(
            complete_structured_with_retry(
                llm,
                messages=[Message(role="user", content="find data")],
                response_model=DiscoverySelection,
                max_attempts=2,
            )
        )

    assert len(llm.calls) == 2


def test_retry_rejects_non_positive_max_attempts() -> None:
    llm = FakeLLMClient([{"datasets": ["sessions"], "rationale": "activity"}])

    with pytest.raises(ValueError, match="max_attempts"):
        asyncio.run(
            complete_structured_with_retry(
                llm,
                messages=[Message(role="user", content="find data")],
                response_model=DiscoverySelection,
                max_attempts=0,
            )
        )

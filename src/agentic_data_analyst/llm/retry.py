"""Retry a structured completion, feeding validation failures back to the model."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.llm.base import LLMClient, Message, T


async def complete_structured_with_retry(
    llm: LLMClient,
    *,
    messages: Sequence[Message],
    response_model: type[T],
    check: Callable[[T], None] | None = None,
    max_attempts: int = 1,
) -> T:
    """Call complete_structured, retrying on LLMError with the failure fed back as context.

    'check' runs additional application-level validation on a schema-valid result; it should
    raise LLMError to reject the result and trigger a retry, same as a completion failure.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    conversation: tuple[Message, ...] = tuple(messages)
    for attempt in range(1, max_attempts + 1):
        try:
            result = await llm.complete_structured(messages=conversation, response_model=response_model)
            if check is not None:
                check(result)
            return result
        except LLMError as exc:
            if attempt == max_attempts:
                raise
            conversation = (
                *conversation,
                Message(
                    role="user",
                    content=(
                        f"Your previous response was invalid: {exc}. "
                        "Correct the issue and return a fully valid response."
                    ),
                ),
            )
    raise LLMError("structured completion failed")  # pragma: no cover - loop always returns or raises

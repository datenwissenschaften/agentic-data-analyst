"""Deterministic LLM test double."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel

from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.llm.base import Message, T


class FakeLLMClient:
    """Return queued typed responses and retain calls for assertions."""

    def __init__(self, responses: Iterable[BaseModel | dict[str, Any]]) -> None:
        self._responses = deque(responses)
        self.calls: list[tuple[tuple[Message, ...], type[BaseModel]]] = []

    async def complete_structured(self, *, messages: Sequence[Message], response_model: type[T]) -> T:
        self.calls.append((tuple(messages), response_model))
        if not self._responses:
            raise LLMError("Fake LLM has no queued response")
        response = self._responses.popleft()
        payload = response.model_dump(mode="json") if isinstance(response, BaseModel) else response
        return response_model.model_validate(payload)

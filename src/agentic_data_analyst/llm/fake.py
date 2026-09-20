"""Deterministic LLM test double."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

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
        try:
            payload = response.model_dump_json() if isinstance(response, BaseModel) else json.dumps(response)
            return response_model.model_validate_json(payload)
        except (TypeError, ValidationError) as exc:
            raise LLMError("Fake LLM structured completion failed validation") from exc

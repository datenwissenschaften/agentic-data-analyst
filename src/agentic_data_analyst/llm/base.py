"""Provider-neutral structured completion interface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel

from agentic_data_analyst.models import StrictModel

T = TypeVar("T", bound=BaseModel)


class Message(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMClient(Protocol):
    async def complete_structured(self, *, messages: Sequence[Message], response_model: type[T]) -> T: ...

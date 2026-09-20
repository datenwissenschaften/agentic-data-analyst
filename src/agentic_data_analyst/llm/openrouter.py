"""OpenRouter structured-output client using the OpenAI-compatible endpoint."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import httpx
from pydantic import ValidationError

from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.llm.base import Message, T


class OpenRouterClient:
    """Request strict JSON Schema responses without tying callers to an SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouter API key must not be empty")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._client = client

    async def complete_structured(self, *, messages: Sequence[Message], response_model: type[T]) -> T:
        payload = {
            "model": self._model,
            "messages": [message.model_dump() for message in messages],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__.lower(),
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            },
            "provider": {"require_parameters": True},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            if self._client is not None:
                response = await self._client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        f"{self._base_url}/chat/completions", json=payload, headers=headers
                    )
            response.raise_for_status()
            body = cast(dict[str, Any], response.json())
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("completion content is not text")
            return response_model.model_validate_json(content)
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValidationError) as exc:
            raise LLMError("OpenRouter structured completion failed") from exc

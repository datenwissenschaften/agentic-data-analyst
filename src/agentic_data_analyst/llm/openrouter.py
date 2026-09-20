"""OpenRouter structured-output client using the OpenAI-compatible endpoint."""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence
from typing import Any

import httpx

from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.llm.base import Message, T


def _to_strict_json_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a pydantic schema into the subset OpenAI's strict mode accepts.

    Strict structured outputs require every property to be listed in
    'required' (optionality is expressed via nullable types instead of
    omission), reject the OpenAPI-style 'discriminator'/'oneOf' pydantic
    emits for discriminated unions (using 'anyOf' instead), and reject
    'default' alongside other keywords such as '$ref'.
    """
    node = copy.deepcopy(schema)
    _rewrite_strict_json_schema(node)
    return node


def _rewrite_strict_json_schema(node: object) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"].keys())
        if "oneOf" in node:
            node["anyOf"] = node.pop("oneOf")
        node.pop("discriminator", None)
        node.pop("default", None)
        for value in node.values():
            _rewrite_strict_json_schema(value)
    elif isinstance(node, list):
        for item in node:
            _rewrite_strict_json_schema(item)


class OpenRouterClient:
    """Request strict JSON Schema responses without tying callers to an SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 60.0,
        max_response_bytes: int = 1_000_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenRouter API key must not be empty")
        if not model:
            raise ValueError("OpenRouter model must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("OpenRouter timeout must be greater than zero")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        if max_response_bytes < 1:
            raise ValueError("Maximum response size must be greater than zero")
        self._max_response_bytes = max_response_bytes
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
                    "schema": _to_strict_json_schema(response_model.model_json_schema()),
                },
            },
            "provider": {"require_parameters": True},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        try:
            if self._client is not None:
                response_bytes = await self._post_limited(
                    self._client,
                    payload=payload,
                    headers=headers,
                )
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response_bytes = await self._post_limited(
                        client,
                        payload=payload,
                        headers=headers,
                    )
            body = json.loads(response_bytes)
            if not isinstance(body, dict):
                raise TypeError("completion response is not an object")
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices:
                raise TypeError("completion response has no choices")
            first = choices[0]
            if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
                raise TypeError("completion response has no message")
            content = first["message"].get("content")
            if not isinstance(content, str):
                raise TypeError("completion content is not text")
            return response_model.model_validate_json(content)
        except LLMError:
            raise
        except (httpx.HTTPError, ValueError, TypeError, RecursionError) as exc:
            raise LLMError("OpenRouter structured completion failed") from exc

    async def _post_limited(
        self,
        client: httpx.AsyncClient,
        *,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> bytes:
        async with client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=self._timeout,
        ) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    declared_length = int(content_length)
                except ValueError as exc:
                    raise LLMError("OpenRouter returned an invalid content length") from exc
                if declared_length > self._max_response_bytes:
                    raise LLMError("OpenRouter response exceeded the configured size limit")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self._max_response_bytes:
                    raise LLMError("OpenRouter response exceeded the configured size limit")
            if not body:
                raise LLMError("OpenRouter returned an empty response")
            return bytes(body)

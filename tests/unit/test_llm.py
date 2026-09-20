import asyncio
import json

import httpx
import pytest

from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.llm import FakeLLMClient, Message, OpenRouterClient
from agentic_data_analyst.models import DiscoverySelection


def test_fake_llm_validates_queued_data() -> None:
    client = FakeLLMClient([{"datasets": ["sessions"], "rationale": "Sessions measure activity."}])

    result = asyncio.run(
        client.complete_structured(
            messages=[Message(role="user", content="retention")],
            response_model=DiscoverySelection,
        )
    )

    assert result.datasets == ("sessions",)
    assert client.calls[0][1] is DiscoverySelection


def test_openrouter_requests_strict_json_schema() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"datasets": ["sessions"], "rationale": "Activity source"})
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    client = OpenRouterClient(api_key="test-key", model="test/model", client=async_client)
    try:
        result = asyncio.run(
            client.complete_structured(
                messages=[Message(role="user", content="find data")],
                response_model=DiscoverySelection,
            )
        )
    finally:
        asyncio.run(async_client.aclose())

    assert result.datasets == ("sessions",)
    assert captured["response_format"]["type"] == "json_schema"  # type: ignore[index]
    assert captured["response_format"]["json_schema"]["strict"] is True  # type: ignore[index]


def _complete_with_handler(
    handler: httpx.MockTransport,
    *,
    max_response_bytes: int = 1_000_000,
) -> DiscoverySelection:
    async_client = httpx.AsyncClient(transport=handler)
    client = OpenRouterClient(
        api_key="super-secret-test-key",
        model="test/model",
        client=async_client,
        timeout_seconds=0.1,
        max_response_bytes=max_response_bytes,
    )
    try:
        return asyncio.run(
            client.complete_structured(
                messages=[Message(role="user", content="find data")],
                response_model=DiscoverySelection,
            )
        )
    finally:
        asyncio.run(async_client.aclose())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"datasets": [], "rationale": "none"})}}]},
        ),
        httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "datasets": ["sessions"],
                                    "rationale": "activity",
                                    "unexpected": "field",
                                }
                            )
                        }
                    }
                ]
            },
        ),
        httpx.Response(200, content=b""),
        httpx.Response(500, json={"error": {"message": "upstream included secret"}}),
    ],
)
def test_openrouter_fails_cleanly_for_malformed_http_responses(response: httpx.Response) -> None:
    transport = httpx.MockTransport(lambda request: response)

    with pytest.raises(LLMError) as captured:
        _complete_with_handler(transport)

    assert "super-secret-test-key" not in str(captured.value)


def test_openrouter_maps_timeout_without_exposing_key() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        assert request.extensions["timeout"]["read"] == 0.1  # type: ignore[index]
        raise httpx.ReadTimeout("timed out with upstream details", request=request)

    with pytest.raises(LLMError) as captured:
        _complete_with_handler(httpx.MockTransport(timeout))

    assert "super-secret-test-key" not in str(captured.value)


def test_openrouter_rejects_response_over_size_limit() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"x" * 101))

    with pytest.raises(LLMError, match="size limit"):
        _complete_with_handler(transport, max_response_bytes=100)


def test_fake_llm_rejects_unknown_fields_as_provider_error() -> None:
    client = FakeLLMClient(
        [
            {
                "datasets": ["sessions"],
                "rationale": "activity",
                "unexpected": "field",
            }
        ]
    )

    with pytest.raises(LLMError, match="failed validation"):
        asyncio.run(
            client.complete_structured(
                messages=[Message(role="user", content="find data")],
                response_model=DiscoverySelection,
            )
        )

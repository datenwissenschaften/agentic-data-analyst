import asyncio
import json

import httpx

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

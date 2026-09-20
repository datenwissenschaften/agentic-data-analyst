import asyncio
from typing import cast

import httpx

from agentic_data_analyst.api.app import create_app
from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.models import AnalyticsQuestion
from agentic_data_analyst.workflow import AnalysisWorkflow


class FailingWorkflow:
    async def analyze(self, request: AnalyticsQuestion) -> None:
        raise LLMError("provider unavailable")


def test_health_does_not_initialize_external_dependencies() -> None:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agentic-data-analyst"}


def test_analysis_maps_provider_failure_without_exposing_traceback() -> None:
    app = create_app(cast(AnalysisWorkflow, FailingWorkflow()))

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/analysis", json={"question": "Show session trends"})

    response = asyncio.run(request())

    assert response.status_code == 502
    assert response.json() == {"detail": "provider unavailable"}

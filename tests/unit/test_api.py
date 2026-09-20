import asyncio
import importlib
from typing import cast

import httpx
import pytest

from agentic_data_analyst.api.app import create_app
from agentic_data_analyst.errors import (
    CatalogError,
    ExecutionError,
    ExecutionTimeoutError,
    LLMError,
    UnsafeAnalysisError,
)
from agentic_data_analyst.models import AnalyticsQuestion
from agentic_data_analyst.workflow import AnalysisWorkflow


class FailingWorkflow:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.closed = False

    async def analyze(self, request: AnalyticsQuestion) -> None:
        raise self._error

    def close(self) -> None:
        self.closed = True


def _request(
    app: object,
    method: str,
    path: str,
    *,
    json: object | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.request(method, path, json=json)

    return asyncio.run(send())


def test_health_response() -> None:
    app = create_app(cast(AnalysisWorkflow, FailingWorkflow(RuntimeError("not called"))))

    response = _request(app, "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agentic-data-analyst"}


@pytest.mark.parametrize(
    ("error", "status_code", "code", "message"),
    [
        (LLMError("provider secret"), 502, "llm_error", "Model completion failed"),
        (CatalogError("internal path"), 503, "catalog_error", "Catalog operation failed"),
        (UnsafeAnalysisError("rejected"), 422, "unsafe_analysis", "rejected"),
        (ExecutionError("internal Spark path"), 500, "execution_error", "Analysis execution failed"),
        (
            ExecutionTimeoutError("internal timeout"),
            504,
            "execution_timeout",
            "Analysis execution timed out",
        ),
        (RuntimeError("unexpected secret"), 500, "internal_error", "Internal server error"),
    ],
)
def test_analysis_returns_stable_sanitized_errors(
    error: Exception, status_code: int, code: str, message: str
) -> None:
    app = create_app(cast(AnalysisWorkflow, FailingWorkflow(error)))

    response = _request(app, "POST", "/analysis", json={"question": "Show session trends"})

    assert response.status_code == status_code
    assert response.json() == {"error": {"code": code, "message": message}}
    assert "Traceback" not in response.text
    assert "unexpected secret" not in response.text
    assert "provider secret" not in response.text
    assert "internal path" not in response.text


def test_request_validation_is_bounded_and_does_not_echo_input() -> None:
    oversized = "secret-contents-" * 200

    response = _request(
        create_app(cast(AnalysisWorkflow, FailingWorkflow(RuntimeError("not called")))),
        "POST",
        "/analysis",
        json={"question": oversized},
    )

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "invalid_request", "message": "Request validation failed"}}
    assert "secret-contents" not in response.text


def test_owned_workflow_is_closed_by_application_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    module = importlib.import_module("agentic_data_analyst.api.app")
    workflow = FailingWorkflow(RuntimeError("unused"))
    monkeypatch.setattr(module, "build_workflow", lambda settings: workflow)
    app = module.create_app()

    async def run_lifespan() -> None:
        async with app.router.lifespan_context(app):
            assert app.state.workflow is workflow
            assert not workflow.closed

    asyncio.run(run_lifespan())

    assert workflow.closed

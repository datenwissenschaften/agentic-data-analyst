"""FastAPI transport with explicit lifecycle and stable error responses."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agentic_data_analyst.bootstrap import build_workflow
from agentic_data_analyst.config import Settings
from agentic_data_analyst.errors import (
    AnalystError,
    CatalogError,
    ExecutionError,
    ExecutionTimeoutError,
    LLMError,
    UnsafeAnalysisError,
)
from agentic_data_analyst.models import AnalysisResponse, AnalyticsQuestion, StrictModel
from agentic_data_analyst.workflow import AnalysisWorkflow


class HealthResponse(StrictModel):
    status: str
    service: str


class ErrorDetail(StrictModel):
    code: str
    message: str


class ErrorResponse(StrictModel):
    error: ErrorDetail


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    body = ErrorResponse(error=ErrorDetail(code=code, message=message))
    return JSONResponse(status_code=status_code, content=body.model_dump())


def create_app(workflow: AnalysisWorkflow | None = None) -> FastAPI:
    owned_workflow = workflow is None

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if owned_workflow:
            application.state.workflow = build_workflow(Settings.from_env())
        try:
            yield
        finally:
            if owned_workflow and hasattr(application.state, "workflow"):
                application.state.workflow.close()

    application = FastAPI(
        title="Agentic Data Analyst",
        version="0.1.0",
        description="Validated natural-language-to-PySpark analytics",
        lifespan=lifespan,
    )
    if workflow is not None:
        application.state.workflow = workflow

    @application.exception_handler(RequestValidationError)
    async def request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        del request, exc
        return _error_response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_request",
            "Request validation failed",
        )

    @application.exception_handler(UnsafeAnalysisError)
    async def unsafe_analysis(request: Request, exc: UnsafeAnalysisError) -> JSONResponse:
        del request
        return _error_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "unsafe_analysis", str(exc))

    @application.exception_handler(LLMError)
    async def llm_error(request: Request, exc: LLMError) -> JSONResponse:
        del request, exc
        return _error_response(status.HTTP_502_BAD_GATEWAY, "llm_error", "Model completion failed")

    @application.exception_handler(CatalogError)
    async def catalog_error(request: Request, exc: CatalogError) -> JSONResponse:
        del request, exc
        return _error_response(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "catalog_error",
            "Catalog operation failed",
        )

    @application.exception_handler(ExecutionError)
    async def execution_error(request: Request, exc: ExecutionError) -> JSONResponse:
        del request, exc
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "execution_error",
            "Analysis execution failed",
        )

    @application.exception_handler(ExecutionTimeoutError)
    async def execution_timeout(request: Request, exc: ExecutionTimeoutError) -> JSONResponse:
        del request, exc
        return _error_response(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "execution_timeout",
            "Analysis execution timed out",
        )

    @application.exception_handler(AnalystError)
    async def analyst_error(request: Request, exc: AnalystError) -> JSONResponse:
        del request, exc
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "analyst_error",
            "Analysis request failed",
        )

    @application.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        del request, exc
        return _error_response(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "internal_error",
            "Internal server error",
        )

    error_responses: dict[int | str, dict[str, Any]] = {
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    }

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="agentic-data-analyst")

    @application.post(
        "/analysis",
        response_model=AnalysisResponse,
        responses=error_responses,
    )
    async def analyze(request: AnalyticsQuestion) -> AnalysisResponse:
        service: AnalysisWorkflow = application.state.workflow
        return await service.analyze(request)

    return application


app = create_app()

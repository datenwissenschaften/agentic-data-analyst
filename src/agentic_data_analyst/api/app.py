"""FastAPI transport with injectable workflow dependencies."""

from __future__ import annotations

from functools import lru_cache

from fastapi import FastAPI, HTTPException, status

from agentic_data_analyst.bootstrap import build_workflow
from agentic_data_analyst.config import Settings
from agentic_data_analyst.errors import (
    CatalogError,
    ExecutionError,
    LLMError,
    UnsafeAnalysisError,
)
from agentic_data_analyst.models import AnalysisResponse, AnalyticsQuestion, StrictModel
from agentic_data_analyst.workflow import AnalysisWorkflow


class HealthResponse(StrictModel):
    status: str
    service: str


@lru_cache(maxsize=1)
def _default_workflow() -> AnalysisWorkflow:
    return build_workflow(Settings.from_env())


def create_app(workflow: AnalysisWorkflow | None = None) -> FastAPI:
    application = FastAPI(
        title="Agentic Data Analyst",
        version="0.1.0",
        description="Validated natural-language-to-PySpark analytics",
    )

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok", service="agentic-data-analyst")

    @application.post("/analysis", response_model=AnalysisResponse)
    async def analyze(request: AnalyticsQuestion) -> AnalysisResponse:
        try:
            service = workflow if workflow is not None else _default_workflow()
            return await service.analyze(request)
        except UnsafeAnalysisError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except LLMError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
        except CatalogError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        except ExecutionError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Analysis execution failed",
            ) from exc

    return application


app = create_app()

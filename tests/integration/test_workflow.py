import asyncio
from pathlib import Path

import httpx
import pytest

from agentic_data_analyst.agents import (
    GenerationAgent,
    InterpretationAgent,
    MetadataDiscoveryAgent,
    PlanningAgent,
)
from agentic_data_analyst.api.app import create_app
from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.execution import SparkAnalysisRunner, SparkCompiler, SparkSessionFactory
from agentic_data_analyst.guardrails import AnalysisValidator
from agentic_data_analyst.llm import FakeLLMClient
from agentic_data_analyst.workflow import AnalysisWorkflow


@pytest.mark.integration
def test_natural_language_to_executed_spark_result(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
    spark_sessions: SparkSessionFactory,
    llm_responses: tuple[object, ...],
) -> None:
    llm = FakeLLMClient(llm_responses)
    validator = AnalysisValidator(catalog, approved_data_root=sample_data_dir)
    compiler = SparkCompiler(catalog)
    workflow = AnalysisWorkflow(
        catalog=catalog,
        discovery=MetadataDiscoveryAgent(llm),
        planner=PlanningAgent(llm),
        generator=GenerationAgent(llm),
        validator=validator,
        compiler=compiler,
        runner=SparkAnalysisRunner(
            validator=validator,
            compiler=compiler,
            session_factory=spark_sessions,
        ),
        interpreter=InterpretationAgent(llm),
        max_result_rows=100,
    )

    app = create_app(workflow)

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/analysis",
                json={"question": "What is average session duration by player segment?"},
            )

    response = asyncio.run(request())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["validation"]["is_valid"] is True
    assert body["datasets_used"] == ["players", "sessions"]
    assert body["result"]["row_count"] == 3
    assert len(llm.calls) == 4
    assert set(body["stage_durations_ms"]) == {
        "discovery",
        "planning",
        "generation",
        "validation",
        "execution",
        "interpretation",
    }

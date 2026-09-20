import asyncio

import pytest

from agentic_data_analyst.agents import GenerationAgent, MetadataDiscoveryAgent, PlanningAgent
from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.llm import FakeLLMClient
from agentic_data_analyst.models import (
    AnalysisIR,
    AnalysisPlan,
    AnalyticsQuestion,
    CatalogCandidate,
    DatasetSelection,
)


def test_discovery_rejects_hallucinated_dataset() -> None:
    llm = FakeLLMClient([{"datasets": ["secret_table"], "rationale": "bad"}])
    agent = MetadataDiscoveryAgent(llm)

    with pytest.raises(LLMError, match="outside the candidate"):
        asyncio.run(
            agent.select(
                AnalyticsQuestion(question="Show activity"),
                [CatalogCandidate(name="sessions", description="activity")],
            )
        )


def test_planner_receives_selected_schema_without_physical_path(
    analysis_plan: AnalysisPlan, catalog: LocalParquetCatalog
) -> None:
    metadata = (catalog.get_dataset("players"), catalog.get_dataset("sessions"))
    llm = FakeLLMClient([analysis_plan])

    result = asyncio.run(
        PlanningAgent(llm).plan(AnalyticsQuestion(question="Average duration by segment"), metadata)
    )

    assert result.datasets[0] == DatasetSelection(
        dataset="players",
        alias="p",
        columns=("player_id", "segment"),
        rationale="Provides player segment.",
    )
    assert '"path"' not in llm.calls[0][0][1].content


def test_planner_rejects_unknown_columns(catalog: LocalParquetCatalog) -> None:
    invalid_plan = {
        "objective": "read a secret",
        "datasets": [
            {
                "dataset": "players",
                "alias": "p",
                "columns": ["password"],
                "rationale": "requested",
            }
        ],
        "steps": ["read password"],
        "result_grain": "one row",
        "expected_columns": ["password"],
    }

    with pytest.raises(LLMError, match="unknown columns"):
        asyncio.run(
            PlanningAgent(FakeLLMClient([invalid_plan])).plan(
                AnalyticsQuestion(question="Show passwords"),
                [catalog.get_dataset("players")],
            )
        )


def test_generation_rejects_inputs_that_differ_from_plan(
    analysis_plan: AnalysisPlan,
    analysis_ir: AnalysisIR,
    catalog: LocalParquetCatalog,
) -> None:
    changed = analysis_ir.model_copy(update={"inputs": analysis_ir.inputs[:1]})
    metadata = (catalog.get_dataset("players"), catalog.get_dataset("sessions"))

    with pytest.raises(LLMError, match="differ from"):
        asyncio.run(
            GenerationAgent(FakeLLMClient([changed])).generate(
                AnalyticsQuestion(question="Average duration by segment"),
                analysis_plan,
                metadata,
                max_result_rows=100,
            )
        )

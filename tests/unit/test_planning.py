import asyncio

import pytest

from agentic_data_analyst.agents import MetadataDiscoveryAgent, PlanningAgent
from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.llm import FakeLLMClient
from agentic_data_analyst.models import (
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
    analysis_plan: AnalysisPlan, catalog: object
) -> None:
    typed_catalog = catalog
    metadata = (typed_catalog.get_dataset("players"), typed_catalog.get_dataset("sessions"))
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

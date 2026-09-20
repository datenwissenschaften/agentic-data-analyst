"""Metadata discovery and analysis planning stages."""

from __future__ import annotations

import json
from collections.abc import Sequence

from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.llm.base import LLMClient, Message
from agentic_data_analyst.models import (
    AnalysisPlan,
    AnalyticsQuestion,
    CatalogCandidate,
    DatasetMetadata,
    DiscoverySelection,
)


class MetadataDiscoveryAgent:
    """Select likely datasets from lightweight catalog search results."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def select(
        self, question: AnalyticsQuestion, candidates: Sequence[CatalogCandidate]
    ) -> DiscoverySelection:
        if not candidates:
            raise LLMError("Catalog search returned no candidate datasets")
        response = await self._llm.complete_structured(
            messages=(
                Message(
                    role="system",
                    content=(
                        "Select only the catalog datasets needed to answer the question. "
                        "Use only names present in the candidates. Prefer the smallest sufficient set."
                    ),
                ),
                Message(
                    role="user",
                    content=json.dumps(
                        {
                            "question": question.question,
                            "candidates": [candidate.model_dump() for candidate in candidates],
                        },
                        default=str,
                    ),
                ),
            ),
            response_model=DiscoverySelection,
        )
        allowed = {candidate.name for candidate in candidates}
        unknown = set(response.datasets) - allowed
        if unknown:
            raise LLMError(f"Discovery selected datasets outside the candidate set: {sorted(unknown)}")
        return response


class PlanningAgent:
    """Create an executable-grain plan from only the selected schemas."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def plan(self, question: AnalyticsQuestion, metadata: Sequence[DatasetMetadata]) -> AnalysisPlan:
        schemas = [dataset.model_dump(exclude={"path"}) for dataset in metadata]
        plan = await self._llm.complete_structured(
            messages=(
                Message(
                    role="system",
                    content=(
                        "Create a precise analytics plan using only the supplied datasets and columns. "
                        "Give each dataset a short unique alias. Do not invent schema."
                    ),
                ),
                Message(
                    role="user",
                    content=json.dumps({"question": question.question, "schemas": schemas}, default=str),
                ),
            ),
            response_model=AnalysisPlan,
        )
        available = {dataset.name: {column.name for column in dataset.columns} for dataset in metadata}
        for selected in plan.datasets:
            if selected.dataset not in available:
                raise LLMError(f"Plan references undiscovered dataset: {selected.dataset}")
            unknown = set(selected.columns) - available[selected.dataset]
            if unknown:
                raise LLMError(f"Plan references unknown columns in {selected.dataset}: {sorted(unknown)}")
        if len({selected.alias for selected in plan.datasets}) != len(plan.datasets):
            raise LLMError("Plan contains duplicate dataset aliases")
        return plan

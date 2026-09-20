"""Result interpretation stage."""

from __future__ import annotations

import json

from agentic_data_analyst.llm.base import LLMClient, Message
from agentic_data_analyst.models import (
    AnalysisPlan,
    AnalyticsQuestion,
    ExecutionResult,
    ResultExplanation,
)


class InterpretationAgent:
    """Explain materialized rows without exposing prompts through the API."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def explain(self, question: AnalyticsQuestion, plan: AnalysisPlan, result: ExecutionResult) -> str:
        response = await self._llm.complete_structured(
            messages=(
                Message(
                    role="system",
                    content=(
                        "Explain the analytical result concisely. State what the returned rows show, "
                        "preserve units, and avoid claims not supported by the data."
                    ),
                ),
                Message(
                    role="user",
                    content=json.dumps(
                        {
                            "question": question.question,
                            "objective": plan.objective,
                            "result": result.model_dump(mode="json"),
                        }
                    ),
                ),
            ),
            response_model=ResultExplanation,
        )
        return response.summary

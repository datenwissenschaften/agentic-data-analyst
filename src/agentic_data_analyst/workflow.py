"""Observable orchestration of the analytics stages."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from agentic_data_analyst.agents import (
    GenerationAgent,
    InterpretationAgent,
    MetadataDiscoveryAgent,
    PlanningAgent,
)
from agentic_data_analyst.catalog.base import Catalog
from agentic_data_analyst.errors import UnsafeAnalysisError
from agentic_data_analyst.execution.compiler import SparkCompiler
from agentic_data_analyst.execution.runner import SparkAnalysisRunner
from agentic_data_analyst.guardrails.validator import AnalysisValidator
from agentic_data_analyst.models import (
    AnalysisResponse,
    AnalyticsQuestion,
    GeneratedAnalysis,
)
from agentic_data_analyst.policy import AnalysisPolicy

StageObserver = Callable[[str, int], None]


class AnalysisWorkflow:
    """Coordinate explicit stages and expose their timings."""

    def __init__(
        self,
        *,
        catalog: Catalog,
        discovery: MetadataDiscoveryAgent,
        planner: PlanningAgent,
        generator: GenerationAgent,
        validator: AnalysisValidator,
        compiler: SparkCompiler,
        runner: SparkAnalysisRunner,
        interpreter: InterpretationAgent | None,
        policy: AnalysisPolicy | None = None,
        observer: StageObserver | None = None,
    ) -> None:
        self._catalog = catalog
        self._discovery = discovery
        self._planner = planner
        self._generator = generator
        self._validator = validator
        self._compiler = compiler
        self._runner = runner
        self._interpreter = interpreter
        self._policy = policy or AnalysisPolicy()
        self._observer = observer

    async def analyze(self, request: AnalyticsQuestion) -> AnalysisResponse:
        durations: dict[str, int] = {}

        started = time.perf_counter()
        candidates = self._catalog.search(request.question, limit=self._policy.max_catalog_candidates)
        if not candidates:
            candidates = self._catalog.list_datasets()[: self._policy.max_catalog_candidates]
        selection = await self._discovery.select(request, candidates)
        self._record("discovery", started, durations)

        metadata = tuple(self._catalog.get_dataset(name) for name in selection.datasets)
        started = time.perf_counter()
        plan = await self._planner.plan(request, metadata)
        self._record("planning", started, durations)

        started = time.perf_counter()
        ir = await self._generator.generate(
            request, plan, metadata, max_result_rows=self._policy.max_result_rows
        )
        self._record("generation", started, durations)

        started = time.perf_counter()
        outcome = self._validator.authorize(ir)
        validation = outcome.result
        self._record("validation", started, durations)
        if not validation.is_valid or outcome.analysis is None:
            codes = ", ".join(issue.code for issue in validation.issues)
            raise UnsafeAnalysisError(f"Generated analysis was rejected: {codes}")
        if tuple(plan.expected_columns) != outcome.analysis.output_columns:
            raise UnsafeAnalysisError("Generated output columns differ from the validated analysis plan")
        generated = GeneratedAnalysis(
            ir=ir,
            pyspark_preview=self._compiler.render(outcome.analysis),
        )

        started = time.perf_counter()
        result = await asyncio.to_thread(self._runner.execute, ir)
        self._record("execution", started, durations)

        explanation: str | None = None
        if self._interpreter is not None:
            started = time.perf_counter()
            explanation = await self._interpreter.explain(request, plan, result)
            self._record("interpretation", started, durations)

        return AnalysisResponse(
            question=request.question,
            plan=plan,
            datasets_used=tuple(selected.dataset for selected in plan.datasets),
            generated_analysis=generated,
            validation=validation,
            result=result,
            explanation=explanation,
            stage_durations_ms=durations,
        )

    def close(self) -> None:
        self._runner.close()

    def _record(self, name: str, started: float, durations: dict[str, int]) -> None:
        duration = round((time.perf_counter() - started) * 1_000)
        durations[name] = duration
        if self._observer is not None:
            self._observer(name, duration)

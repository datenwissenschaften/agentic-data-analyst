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
        max_result_rows: int,
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
        self._max_result_rows = max_result_rows
        self._observer = observer

    async def analyze(self, request: AnalyticsQuestion) -> AnalysisResponse:
        durations: dict[str, int] = {}

        started = time.perf_counter()
        candidates = self._catalog.search(request.question, limit=8)
        if not candidates:
            candidates = self._catalog.list_datasets()[:8]
        selection = await self._discovery.select(request, candidates)
        self._record("discovery", started, durations)

        metadata = tuple(self._catalog.get_dataset(name) for name in selection.datasets)
        started = time.perf_counter()
        plan = await self._planner.plan(request, metadata)
        self._record("planning", started, durations)

        started = time.perf_counter()
        ir = await self._generator.generate(request, plan, metadata, max_result_rows=self._max_result_rows)
        generated = GeneratedAnalysis(ir=ir, pyspark_preview=self._compiler.render(ir))
        self._record("generation", started, durations)

        started = time.perf_counter()
        validation = self._validator.validate(ir)
        self._record("validation", started, durations)
        if not validation.is_valid:
            codes = ", ".join(issue.code for issue in validation.issues)
            raise UnsafeAnalysisError(f"Generated analysis was rejected: {codes}")

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

    def _record(self, name: str, started: float, durations: dict[str, int]) -> None:
        duration = round((time.perf_counter() - started) * 1_000)
        durations[name] = duration
        if self._observer is not None:
            self._observer(name, duration)

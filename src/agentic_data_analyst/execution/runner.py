"""Controlled Spark lifecycle and result materialization."""

from __future__ import annotations

import threading
import time
from datetime import date, datetime
from decimal import Decimal

from pyspark.sql import SparkSession

from agentic_data_analyst.errors import ExecutionError, UnsafeAnalysisError
from agentic_data_analyst.execution.compiler import SparkCompiler
from agentic_data_analyst.guardrails.validator import AnalysisValidator
from agentic_data_analyst.models import AnalysisIR, ExecutionResult, LimitStep, ResultValue


class SparkSessionFactory:
    """Lazily create one local Spark session per application process."""

    def __init__(self, *, master: str = "local[2]", app_name: str = "agentic-data-analyst") -> None:
        self._master = master
        self._app_name = app_name
        self._session: SparkSession | None = None
        self._lock = threading.Lock()

    def get(self) -> SparkSession:
        with self._lock:
            if self._session is None:
                self._session = (
                    SparkSession.builder.master(self._master)
                    .appName(self._app_name)
                    .config("spark.driver.bindAddress", "127.0.0.1")
                    .config("spark.driver.host", "127.0.0.1")
                    .config("spark.ui.enabled", "false")
                    .config("spark.sql.shuffle.partitions", "4")
                    .config("spark.sql.session.timeZone", "UTC")
                    .config("spark.sql.ansi.enabled", "true")
                    .getOrCreate()
                )
                self._session.sparkContext.setLogLevel("ERROR")
            return self._session

    def stop(self) -> None:
        with self._lock:
            if self._session is not None:
                self._session.stop()
                self._session = None


class SparkAnalysisRunner:
    """Revalidate, compile, execute, and bound result collection."""

    def __init__(
        self,
        *,
        validator: AnalysisValidator,
        compiler: SparkCompiler,
        session_factory: SparkSessionFactory,
        max_result_rows: int = 100,
    ) -> None:
        self._validator = validator
        self._compiler = compiler
        self._sessions = session_factory
        self._max_result_rows = max_result_rows

    def execute(self, ir: AnalysisIR) -> ExecutionResult:
        validation = self._validator.validate(ir)
        if not validation.is_valid:
            codes = ", ".join(issue.code for issue in validation.issues)
            raise UnsafeAnalysisError(f"Analysis validation failed: {codes}")
        started = time.perf_counter()
        try:
            final_limit = ir.steps[-1]
            if not isinstance(final_limit, LimitStep):
                raise UnsafeAnalysisError("Validated analysis is missing its final limit")
            pre_limit_ir = ir.model_copy(update={"steps": ir.steps[:-1], "output": final_limit.input})
            frame = self._compiler.compile(pre_limit_ir, self._sessions.get())
            result_limit = min(final_limit.count, self._max_result_rows)
            collected = frame.limit(result_limit + 1).collect()
        except Exception as exc:
            raise ExecutionError("Spark analysis execution failed") from exc
        truncated = len(collected) > result_limit
        rows = collected[:result_limit]
        normalized = tuple(
            {key: self._normalize(value) for key, value in row.asDict(recursive=True).items()} for row in rows
        )
        return ExecutionResult(
            columns=tuple(frame.columns),
            rows=normalized,
            row_count=len(normalized),
            truncated=truncated,
            duration_ms=round((time.perf_counter() - started) * 1_000),
        )

    @staticmethod
    def _normalize(value: object) -> ResultValue:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        return str(value)

"""Controlled Spark lifecycle and result materialization."""

from __future__ import annotations

import threading
import time
import uuid
from contextlib import suppress
from datetime import date, datetime
from decimal import Decimal
from math import isfinite

from pyspark.sql import SparkSession

from agentic_data_analyst.errors import ExecutionError, ExecutionTimeoutError, UnsafeAnalysisError
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
        execution_timeout_seconds: float | None = None,
    ) -> None:
        self._validator = validator
        self._compiler = compiler
        self._sessions = session_factory
        self._execution_timeout_seconds = execution_timeout_seconds

    def execute(self, ir: AnalysisIR) -> ExecutionResult:
        outcome = self._validator.authorize(ir)
        if not outcome.result.is_valid or outcome.analysis is None:
            codes = ", ".join(issue.code for issue in outcome.result.issues)
            raise UnsafeAnalysisError(f"Analysis validation failed: {codes}")
        started = time.perf_counter()
        timed_out = threading.Event()
        timer: threading.Timer | None = None
        job_group = f"agentic-data-analyst-{uuid.uuid4()}"
        try:
            spark = self._sessions.get()
            spark.sparkContext.setJobGroup(
                job_group,
                "Validated agentic analytics request",
                interruptOnCancel=True,
            )
        except Exception as exc:
            raise ExecutionError("Spark session initialization failed") from exc
        if self._execution_timeout_seconds is not None:
            timer = threading.Timer(
                self._execution_timeout_seconds,
                self._cancel_job,
                args=(spark, job_group, timed_out),
            )
            timer.daemon = True
            timer.start()
        try:
            final_limit = outcome.analysis.ir.steps[-1]
            if not isinstance(final_limit, LimitStep):
                raise UnsafeAnalysisError("Validated analysis is missing its final limit")
            pre_limit = outcome.analysis.before_final_limit()
            frame = self._compiler.compile(pre_limit, spark)
            if tuple(frame.columns) != outcome.analysis.output_columns:
                raise ExecutionError("Compiled output schema differs from validated lineage")
            result_limit = final_limit.count
            collected = frame.limit(result_limit + 1).collect()
            if timed_out.is_set():
                raise ExecutionTimeoutError("Spark analysis exceeded its execution deadline")
        except ExecutionTimeoutError:
            raise
        except ExecutionError:
            raise
        except Exception as exc:
            if timed_out.is_set():
                raise ExecutionTimeoutError("Spark analysis exceeded its execution deadline") from exc
            raise ExecutionError("Spark analysis execution failed") from exc
        finally:
            if timer is not None:
                timer.cancel()
            with suppress(Exception):
                spark.sparkContext.setLocalProperty("spark.jobGroup.id", None)  # type: ignore[arg-type]
                spark.sparkContext.setLocalProperty("spark.job.description", None)  # type: ignore[arg-type]
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

    def close(self) -> None:
        self._sessions.stop()

    @staticmethod
    def _cancel_job(spark: SparkSession, job_group: str, timed_out: threading.Event) -> None:
        timed_out.set()
        with suppress(Exception):
            spark.sparkContext.cancelJobGroup(job_group)

    @staticmethod
    def _normalize(value: object) -> ResultValue:
        if isinstance(value, float) and not isfinite(value):
            return str(value)
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        if isinstance(value, Decimal):
            converted = float(value)
            return converted if isfinite(converted) else str(value)
        return str(value)

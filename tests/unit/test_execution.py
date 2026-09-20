from __future__ import annotations

import threading
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.errors import ExecutionError, ExecutionTimeoutError, UnsafeAnalysisError
from agentic_data_analyst.execution import SparkAnalysisRunner, SparkCompiler, SparkSessionFactory
from agentic_data_analyst.guardrails import AnalysisValidator
from agentic_data_analyst.guardrails.validated import ValidatedAnalysis
from agentic_data_analyst.models import (
    AggregateExpression,
    AggregateFunction,
    AggregateStep,
    AnalysisIR,
    CatalogCandidate,
    DatasetMetadata,
    DatasetSelection,
    Expression,
    ExpressionOp,
    FilterStep,
    LimitStep,
    NamedExpression,
    ProjectStep,
    SortExpression,
    SortStep,
)


def _column(name: str) -> Expression:
    return Expression(op=ExpressionOp.COLUMN, column=name)


def _literal(value: str | int | float | bool | None) -> Expression:
    return Expression(op=ExpressionOp.LITERAL, value=value)


def _binary(op: ExpressionOp, left: Expression, right: Expression) -> Expression:
    return Expression(op=op, arguments=(left, right))


def test_compiler_renders_reviewable_pyspark_preview(
    catalog: LocalParquetCatalog, sample_data_dir: Path, analysis_ir: AnalysisIR
) -> None:
    outcome = AnalysisValidator(catalog, approved_data_root=sample_data_dir).authorize(analysis_ir)
    assert outcome.analysis is not None

    preview = SparkCompiler().render(outcome.analysis)

    assert 'spark.read.parquet(catalog.get_dataset("players").path)' in preview
    assert ".groupBy(" in preview
    assert ".agg(" in preview
    assert "exec(" not in preview


def test_runner_executes_compiled_dataframe_operations(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
    spark_sessions: SparkSessionFactory,
    analysis_ir: AnalysisIR,
) -> None:
    validator = AnalysisValidator(catalog, approved_data_root=sample_data_dir)
    runner = SparkAnalysisRunner(
        validator=validator,
        compiler=SparkCompiler(),
        session_factory=spark_sessions,
    )

    result = runner.execute(analysis_ir)

    assert result.columns == ("segment", "average_duration", "session_count")
    assert {row["segment"] for row in result.rows} == {"casual", "core", "competitive"}
    assert all(float(row["average_duration"]) > 0 for row in result.rows)


def test_compiler_executes_validated_sort_and_limit_semantics(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
    spark_sessions: SparkSessionFactory,
) -> None:
    ir = _path_only_ir().model_copy(
        update={
            "steps": (
                SortStep(
                    output="sorted",
                    input="p",
                    by=(
                        SortExpression(
                            expression=_column("p__player_id"),
                            direction="asc",
                            nulls="first",
                        ),
                    ),
                ),
                LimitStep(output="result", input="sorted", count=1),
            )
        }
    )
    outcome = AnalysisValidator(catalog, approved_data_root=sample_data_dir).authorize(ir)
    assert outcome.analysis is not None

    rows = SparkCompiler().compile(outcome.analysis, spark_sessions.get()).collect()

    assert len(rows) == 1
    assert rows[0]["p__player_id"] == "player_00000"


def test_every_expression_operation_compiles_and_executes(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
    spark_sessions: SparkSessionFactory,
) -> None:
    duration = _column("s__duration_minutes")
    start = _column("s__session_start")
    end = _column("s__session_end")
    device = _column("s__device")
    positive = _binary(ExpressionOp.GT, duration, _literal(0))
    short = _binary(ExpressionOp.LT, duration, _literal(10_000))
    ir = AnalysisIR(
        inputs=(
            DatasetSelection(
                dataset="sessions",
                alias="s",
                columns=(
                    "duration_minutes",
                    "session_start",
                    "session_end",
                    "device",
                ),
                rationale="exercise expression compilation",
            ),
        ),
        steps=(
            FilterStep(output="filtered", input="s", predicate=positive),
            ProjectStep(
                output="projected",
                input="filtered",
                columns=(
                    NamedExpression(alias="column_value", expression=duration),
                    NamedExpression(alias="literal_value", expression=_literal("safe")),
                    NamedExpression(
                        alias="eq_value", expression=_binary(ExpressionOp.EQ, device, _literal("desktop"))
                    ),
                    NamedExpression(
                        alias="ne_value", expression=_binary(ExpressionOp.NE, device, _literal("unknown"))
                    ),
                    NamedExpression(alias="gt_value", expression=positive),
                    NamedExpression(
                        alias="gte_value", expression=_binary(ExpressionOp.GTE, duration, _literal(0))
                    ),
                    NamedExpression(alias="lt_value", expression=short),
                    NamedExpression(
                        alias="lte_value", expression=_binary(ExpressionOp.LTE, duration, _literal(10_000))
                    ),
                    NamedExpression(
                        alias="and_value",
                        expression=_binary(ExpressionOp.AND, positive, short),
                    ),
                    NamedExpression(
                        alias="or_value",
                        expression=_binary(ExpressionOp.OR, positive, short),
                    ),
                    NamedExpression(
                        alias="not_value",
                        expression=Expression(op=ExpressionOp.NOT, arguments=(positive,)),
                    ),
                    NamedExpression(
                        alias="add_value", expression=_binary(ExpressionOp.ADD, duration, _literal(1))
                    ),
                    NamedExpression(
                        alias="subtract_value",
                        expression=_binary(ExpressionOp.SUBTRACT, duration, _literal(1)),
                    ),
                    NamedExpression(
                        alias="multiply_value",
                        expression=_binary(ExpressionOp.MULTIPLY, duration, _literal(2)),
                    ),
                    NamedExpression(
                        alias="divide_value",
                        expression=_binary(ExpressionOp.DIVIDE, duration, _literal(2)),
                    ),
                    NamedExpression(
                        alias="null_value",
                        expression=Expression(op=ExpressionOp.IS_NULL, arguments=(device,)),
                    ),
                    NamedExpression(
                        alias="not_null_value",
                        expression=Expression(op=ExpressionOp.IS_NOT_NULL, arguments=(device,)),
                    ),
                    NamedExpression(
                        alias="date_value",
                        expression=Expression(op=ExpressionOp.TO_DATE, arguments=(start,)),
                    ),
                    NamedExpression(
                        alias="date_diff_value",
                        expression=Expression(op=ExpressionOp.DATE_DIFF, arguments=(end, start)),
                    ),
                    NamedExpression(
                        alias="date_trunc_value",
                        expression=Expression(op=ExpressionOp.DATE_TRUNC, value="month", arguments=(start,)),
                    ),
                    NamedExpression(
                        alias="coalesce_value",
                        expression=Expression(
                            op=ExpressionOp.COALESCE,
                            arguments=(device, _literal("unknown")),
                        ),
                    ),
                    NamedExpression(
                        alias="when_value",
                        expression=Expression(
                            op=ExpressionOp.WHEN,
                            arguments=(positive, _literal("positive"), _literal("other")),
                        ),
                    ),
                ),
            ),
            LimitStep(output="result", input="projected", count=1),
        ),
        output="result",
    )
    validator = AnalysisValidator(catalog, approved_data_root=sample_data_dir)
    outcome = validator.authorize(ir)
    assert outcome.analysis is not None
    preview = SparkCompiler().render(outcome.analysis)
    runner = SparkAnalysisRunner(
        validator=validator,
        compiler=SparkCompiler(),
        session_factory=spark_sessions,
    )

    result = runner.execute(ir)

    assert result.row_count == 1
    assert result.rows[0]["literal_value"] == "safe"
    assert result.rows[0]["when_value"] == "positive"
    assert set(result.columns) == {column.alias for column in ir.steps[1].columns}
    assert all(f'.alias("{column.alias}")' in preview for column in ir.steps[1].columns)


def test_every_aggregate_function_compiles_and_executes(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
    spark_sessions: SparkSessionFactory,
) -> None:
    ir = AnalysisIR(
        inputs=(
            DatasetSelection(
                dataset="sessions",
                alias="s",
                columns=("device", "player_id", "duration_minutes"),
                rationale="exercise aggregate compilation",
            ),
        ),
        steps=(
            AggregateStep(
                output="metrics",
                input="s",
                group_by=(NamedExpression(alias="device", expression=_column("s__device")),),
                aggregations=(
                    AggregateExpression(alias="rows", function=AggregateFunction.COUNT),
                    AggregateExpression(
                        alias="players",
                        function=AggregateFunction.COUNT_DISTINCT,
                        expression=_column("s__player_id"),
                    ),
                    AggregateExpression(
                        alias="total",
                        function=AggregateFunction.SUM,
                        expression=_column("s__duration_minutes"),
                    ),
                    AggregateExpression(
                        alias="average",
                        function=AggregateFunction.AVG,
                        expression=_column("s__duration_minutes"),
                    ),
                    AggregateExpression(
                        alias="minimum",
                        function=AggregateFunction.MIN,
                        expression=_column("s__duration_minutes"),
                    ),
                    AggregateExpression(
                        alias="maximum",
                        function=AggregateFunction.MAX,
                        expression=_column("s__duration_minutes"),
                    ),
                ),
            ),
            LimitStep(output="result", input="metrics", count=10),
        ),
        output="result",
    )
    runner = SparkAnalysisRunner(
        validator=AnalysisValidator(catalog, approved_data_root=sample_data_dir),
        compiler=SparkCompiler(),
        session_factory=spark_sessions,
    )

    result = runner.execute(ir)

    outcome = AnalysisValidator(catalog, approved_data_root=sample_data_dir).authorize(ir)
    assert outcome.analysis is not None
    preview = SparkCompiler().render(outcome.analysis)

    assert result.row_count == 3
    assert all(int(row["rows"]) > 0 for row in result.rows)
    assert all(float(row["minimum"]) <= float(row["maximum"]) for row in result.rows)
    assert all(f"F.{function.value}(" in preview for function in AggregateFunction)


class MutableCatalog:
    def __init__(self, approved: DatasetMetadata, replacement: DatasetMetadata) -> None:
        self._approved = approved
        self._replacement = replacement
        self.calls = 0

    def list_datasets(self) -> tuple[CatalogCandidate, ...]:
        return ()

    def search(self, query: str, *, limit: int = 5) -> tuple[CatalogCandidate, ...]:
        return ()

    def get_dataset(self, name: str) -> DatasetMetadata:
        self.calls += 1
        return self._approved if self.calls == 1 else self._replacement


def test_compiler_uses_path_snapshot_authorized_immediately_before_execution(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
    tmp_path: Path,
    spark_sessions: SparkSessionFactory,
) -> None:
    approved = catalog.get_dataset("players")
    outside = tmp_path / "outside.parquet"
    outside.touch()
    replacement = approved.model_copy(update={"path": str(outside)})
    mutable = MutableCatalog(approved, replacement)
    ir = _path_only_ir()
    runner = SparkAnalysisRunner(
        validator=AnalysisValidator(mutable, approved_data_root=sample_data_dir),
        compiler=SparkCompiler(),
        session_factory=spark_sessions,
    )

    result = runner.execute(ir)

    assert result.row_count == 1
    assert result.truncated
    assert mutable.calls == 1


def _path_only_ir() -> AnalysisIR:
    return AnalysisIR(
        inputs=(
            DatasetSelection(
                dataset="players",
                alias="p",
                columns=("player_id",),
                rationale="path authorization test",
            ),
        ),
        steps=(LimitStep(output="result", input="p", count=1),),
        output="result",
    )


class CancellableSparkContext:
    def __init__(self) -> None:
        self.cancelled = threading.Event()

    def setJobGroup(self, group: str, description: str, *, interruptOnCancel: bool) -> None:
        assert group
        assert description
        assert interruptOnCancel

    def cancelJobGroup(self, group: str) -> None:
        assert group
        self.cancelled.set()

    def setLocalProperty(self, key: str, value: str | None) -> None:
        assert key in {"spark.jobGroup.id", "spark.job.description"}
        assert value is None


class CancellableSpark:
    def __init__(self) -> None:
        self.sparkContext = CancellableSparkContext()


class CancellableSessionFactory:
    def __init__(self) -> None:
        self.session = CancellableSpark()

    def get(self) -> CancellableSpark:
        return self.session

    def stop(self) -> None:
        pass


class BlockingFrame:
    def __init__(self, cancelled: threading.Event) -> None:
        self._cancelled = cancelled
        self.columns = ["p__player_id"]

    def limit(self, count: int) -> BlockingFrame:
        assert count == 2
        return self

    def collect(self) -> list[object]:
        assert self._cancelled.wait(timeout=1)
        raise RuntimeError("cancelled")


class BlockingCompiler:
    def __init__(self, cancelled: threading.Event) -> None:
        self._cancelled = cancelled

    def compile(self, analysis: ValidatedAnalysis, spark: Any) -> BlockingFrame:
        assert analysis.output_columns == ("p__player_id",)
        return BlockingFrame(self._cancelled)


def test_execution_deadline_requests_spark_job_group_cancellation(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
) -> None:
    sessions = CancellableSessionFactory()
    runner = SparkAnalysisRunner(
        validator=AnalysisValidator(catalog, approved_data_root=sample_data_dir),
        compiler=cast(SparkCompiler, BlockingCompiler(sessions.session.sparkContext.cancelled)),
        session_factory=cast(SparkSessionFactory, sessions),
        execution_timeout_seconds=0.01,
    )

    with pytest.raises(ExecutionTimeoutError):
        runner.execute(_path_only_ir())

    assert sessions.session.sparkContext.cancelled.is_set()


def test_runner_rejects_invalid_ir_before_initializing_spark(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
) -> None:
    sessions = CancellableSessionFactory()
    invalid = _path_only_ir().model_copy(
        update={"steps": (LimitStep(output="result", input="missing", count=1),)}
    )
    runner = SparkAnalysisRunner(
        validator=AnalysisValidator(catalog, approved_data_root=sample_data_dir),
        compiler=SparkCompiler(),
        session_factory=cast(SparkSessionFactory, sessions),
    )

    with pytest.raises(UnsafeAnalysisError, match="unknown_relation"):
        runner.execute(invalid)


class WrongSchemaFrame(BlockingFrame):
    def __init__(self) -> None:
        self.columns = ["unexpected"]


class WrongSchemaCompiler:
    def compile(self, analysis: ValidatedAnalysis, spark: Any) -> WrongSchemaFrame:
        return WrongSchemaFrame()


class BrokenSessionFactory:
    def get(self) -> Any:
        raise RuntimeError("session initialization secret")

    def stop(self) -> None:
        pass


class FailingCompiler:
    def compile(self, analysis: ValidatedAnalysis, spark: Any) -> Any:
        raise RuntimeError("compiler secret")


def test_runner_rejects_compiler_lineage_mismatch(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
) -> None:
    sessions = CancellableSessionFactory()
    runner = SparkAnalysisRunner(
        validator=AnalysisValidator(catalog, approved_data_root=sample_data_dir),
        compiler=cast(SparkCompiler, WrongSchemaCompiler()),
        session_factory=cast(SparkSessionFactory, sessions),
    )

    with pytest.raises(ExecutionError, match="schema differs"):
        runner.execute(_path_only_ir())


def test_runner_sanitizes_session_and_compiler_failures(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
) -> None:
    validator = AnalysisValidator(catalog, approved_data_root=sample_data_dir)
    session_runner = SparkAnalysisRunner(
        validator=validator,
        compiler=SparkCompiler(),
        session_factory=cast(SparkSessionFactory, BrokenSessionFactory()),
    )
    with pytest.raises(ExecutionError, match="initialization failed") as session_error:
        session_runner.execute(_path_only_ir())
    assert "secret" not in str(session_error.value)

    sessions = CancellableSessionFactory()
    compiler_runner = SparkAnalysisRunner(
        validator=validator,
        compiler=cast(SparkCompiler, FailingCompiler()),
        session_factory=cast(SparkSessionFactory, sessions),
    )
    with pytest.raises(ExecutionError, match="execution failed") as compiler_error:
        compiler_runner.execute(_path_only_ir())
    assert "secret" not in str(compiler_error.value)


def test_result_normalization_never_emits_nonfinite_json_numbers() -> None:
    assert SparkAnalysisRunner._normalize(float("nan")) == "nan"
    assert SparkAnalysisRunner._normalize(float("inf")) == "inf"
    assert SparkAnalysisRunner._normalize(Decimal("NaN")) == "NaN"

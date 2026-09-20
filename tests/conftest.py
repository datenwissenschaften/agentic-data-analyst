from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.data.generator import generate
from agentic_data_analyst.execution import SparkSessionFactory
from agentic_data_analyst.models import (
    AggregateExpression,
    AggregateFunction,
    AggregateStep,
    AnalysisIR,
    AnalysisPlan,
    DatasetSelection,
    DiscoverySelection,
    Expression,
    ExpressionOp,
    JoinStep,
    LimitStep,
    NamedExpression,
    ResultExplanation,
    SortExpression,
    SortStep,
)


def column(name: str) -> Expression:
    return Expression(op=ExpressionOp.COLUMN, column=name)


@pytest.fixture(scope="session")
def sample_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("catalog")
    generate(path, player_count=60)
    return path


@pytest.fixture
def catalog(sample_data_dir: Path) -> LocalParquetCatalog:
    return LocalParquetCatalog(sample_data_dir)


@pytest.fixture(scope="session")
def spark_sessions() -> Iterator[SparkSessionFactory]:
    factory = SparkSessionFactory(master="local[2]", app_name="agentic-data-analyst-tests")
    yield factory
    factory.stop()


@pytest.fixture
def analysis_plan() -> AnalysisPlan:
    return AnalysisPlan(
        objective="Compare average session duration and session count by player segment.",
        datasets=(
            DatasetSelection(
                dataset="players",
                alias="p",
                columns=("player_id", "segment"),
                rationale="Provides player segment.",
            ),
            DatasetSelection(
                dataset="sessions",
                alias="s",
                columns=("player_id", "duration_minutes"),
                rationale="Provides session duration.",
            ),
        ),
        steps=(
            "Join sessions to players by player_id.",
            "Aggregate average duration and count by segment.",
            "Sort by average duration descending.",
        ),
        result_grain="One row per player segment.",
        expected_columns=("segment", "average_duration", "session_count"),
    )


@pytest.fixture
def analysis_ir(analysis_plan: AnalysisPlan) -> AnalysisIR:
    inputs = analysis_plan.datasets
    return AnalysisIR(
        inputs=inputs,
        steps=(
            JoinStep(
                output="joined",
                left="p",
                right="s",
                condition=Expression(
                    op=ExpressionOp.EQ,
                    arguments=(column("p__player_id"), column("s__player_id")),
                ),
            ),
            AggregateStep(
                output="metrics",
                input="joined",
                group_by=(NamedExpression(alias="segment", expression=column("p__segment")),),
                aggregations=(
                    AggregateExpression(
                        alias="average_duration",
                        function=AggregateFunction.AVG,
                        expression=column("s__duration_minutes"),
                    ),
                    AggregateExpression(
                        alias="session_count",
                        function=AggregateFunction.COUNT,
                        expression=column("s__player_id"),
                    ),
                ),
            ),
            SortStep(
                output="ranked",
                input="metrics",
                by=(SortExpression(expression=column("average_duration"), direction="desc", nulls="last"),),
            ),
            LimitStep(output="result", input="ranked", count=10),
        ),
        output="result",
    )


@pytest.fixture
def llm_responses(analysis_plan: AnalysisPlan, analysis_ir: AnalysisIR) -> tuple[object, ...]:
    return (
        DiscoverySelection(
            datasets=("players", "sessions"),
            rationale="Player segments and session duration are required.",
        ),
        analysis_plan,
        analysis_ir,
        ResultExplanation(summary="The result compares mean session minutes and observed session counts by segment."),
    )

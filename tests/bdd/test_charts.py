import pytest
from plotly.graph_objects import Figure
from pytest_bdd import given, parsers, scenarios, then, when

from agentic_data_analyst.charts import ChartKind, build_figure
from agentic_data_analyst.database import QueryResult

scenarios("features/charts.feature")

type Outcome = Figure | None | ValueError


@given(parsers.parse('a result with the columns "{columns}"'), target_fixture="result")
def result(columns: str) -> QueryResult:
    rows: list[list[str | int | float | bool | None]] = [
        ["2025-Q1", "ai", 410.5],
        ["2025-Q1", "human", 540.2],
        ["2025-Q2", "ai", 398.1],
        ["2025-Q2", "human", 538.7],
    ]
    return QueryResult(columns.split(", "), rows, truncated=False)


def _build(result: QueryResult, kind: ChartKind, x: str, y: str, color: str | None) -> Outcome:
    try:
        return build_figure({"kind": kind, "x": x, "y": y, "color": color, "title": "Test"}, result)
    except ValueError as error:
        return error


@when(
    parsers.re(r'the analyst asks for a "(?P<kind>\w+)" chart of "(?P<y>\w+)" by "(?P<x>\w+)" split by "(?P<color>\w+)"'),
    target_fixture="outcome",
)
def split_chart(result: QueryResult, kind: ChartKind, x: str, y: str, color: str) -> Outcome:
    return _build(result, kind, x, y, color)


@when(parsers.re(r'the analyst asks for a "(?P<kind>\w+)" chart of "(?P<y>\w+)" by "(?P<x>\w+)"$'), target_fixture="outcome")
def plain_chart(result: QueryResult, kind: ChartKind, x: str, y: str) -> Outcome:
    return _build(result, kind, x, y, None)


@then(parsers.parse("the figure has {series:d} series"))
def has_series(outcome: Outcome, series: int) -> None:
    assert isinstance(outcome, Figure), outcome
    assert len(outcome.data) == series


@then(parsers.parse('the chart is rejected with "{text}"'))
def chart_rejected(outcome: Outcome, text: str) -> None:
    if not isinstance(outcome, ValueError):
        pytest.fail(f"Expected a rejection, got {outcome!r}")
    assert text in str(outcome)

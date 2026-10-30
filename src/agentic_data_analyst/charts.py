"""Charts for query results. The model only names the chart kind and columns; the figure is built here from the rows."""

from typing import Literal, TypedDict

import pandas as pd
import plotly.express as px
from plotly.graph_objects import Figure

from agentic_data_analyst.database import QueryResult

type ChartKind = Literal["bar", "line", "scatter"]
CHART_KINDS: tuple[ChartKind, ...] = ("bar", "line", "scatter")
Axis = Literal["x", "y", "color"]
AXES: tuple[Axis, ...] = ("x", "y", "color")


class Chart(TypedDict):
    kind: ChartKind
    x: str
    y: str
    # Splits the rows into one series per value; None for a single series.
    color: str | None
    title: str


def check_chart(chart: Chart, result: QueryResult) -> None:
    """Fail with a message the model can act on when the chart does not fit the result."""
    if chart["kind"] not in CHART_KINDS:
        raise ValueError(f"Unknown chart kind {chart['kind']!r}; use one of {', '.join(CHART_KINDS)}.")
    for axis in AXES:
        column = chart[axis]
        if column is not None and column not in result.columns:
            raise ValueError(f"Chart {axis} column {column!r} is not in the result columns {result.columns}.")


def build_figure(chart: Chart, result: QueryResult) -> Figure | None:
    """The figure, or None when there are no rows to plot."""
    check_chart(chart, result)
    if not result.rows:
        return None
    frame = pd.DataFrame(result.rows, columns=result.columns)
    plot = {"bar": px.bar, "line": px.line, "scatter": px.scatter}[chart["kind"]]
    figure: Figure = plot(frame, x=chart["x"], y=chart["y"], color=chart["color"], title=chart["title"])
    if chart["kind"] == "bar":
        figure.update_layout(barmode="group")
    return figure

"""Compile the closed analysis IR to Spark DataFrame operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pyspark.sql import Column, DataFrame, SparkSession
from pyspark.sql import functions as F

from agentic_data_analyst.guardrails.validated import ValidatedAnalysis
from agentic_data_analyst.models import (
    AggregateExpression,
    AggregateFunction,
    AggregateStep,
    Expression,
    ExpressionOp,
    FilterStep,
    JoinStep,
    LimitStep,
    ProjectStep,
    SortStep,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class SparkCompiler:
    """Translate validated IR nodes directly to Spark's typed DataFrame API."""

    def compile(self, analysis: ValidatedAnalysis, spark: SparkSession) -> DataFrame:
        ir = analysis.ir
        frames: dict[str, DataFrame] = {}
        for selected in ir.inputs:
            authorized = analysis.dataset_for_alias(selected.alias)
            frames[selected.alias] = spark.read.parquet(str(authorized.path)).select(
                *(F.col(column).alias(f"{selected.alias}__{column}") for column in authorized.columns)
            )

        for step in ir.steps:
            if isinstance(step, JoinStep):
                combined = frames[step.left].join(
                    frames[step.right], self._expression(step.condition), step.how
                )
                frames[step.output] = combined
            elif isinstance(step, FilterStep):
                frames[step.output] = frames[step.input].filter(self._expression(step.predicate))
            elif isinstance(step, ProjectStep):
                frames[step.output] = frames[step.input].select(
                    *(self._expression(item.expression).alias(item.alias) for item in step.columns)
                )
            elif isinstance(step, AggregateStep):
                groups = [self._expression(item.expression).alias(item.alias) for item in step.group_by]
                aggregates = [self._aggregate(item) for item in step.aggregations]
                frames[step.output] = frames[step.input].groupBy(*groups).agg(*aggregates)
            elif isinstance(step, SortStep):
                ordering: list[Column] = []
                for item in step.by:
                    column = self._expression(item.expression)
                    if item.direction == "asc":
                        ordering.append(
                            column.asc_nulls_first() if item.nulls == "first" else column.asc_nulls_last()
                        )
                    else:
                        ordering.append(
                            column.desc_nulls_first() if item.nulls == "first" else column.desc_nulls_last()
                        )
                frames[step.output] = frames[step.input].orderBy(*ordering)
            elif isinstance(step, LimitStep):
                frames[step.output] = frames[step.input].limit(step.count)
            else:
                raise ValueError(f"Unsupported analysis step: {type(step).__name__}")
        return frames[ir.output]

    def render(self, analysis: ValidatedAnalysis) -> str:
        """Render equivalent PySpark for review; execution still uses direct compilation."""
        ir = analysis.ir
        lines = [
            "# Generated from validated spark_dataframe_ir/v1",
            "from pyspark.sql import functions as F",
        ]
        for selected in ir.inputs:
            columns = ", ".join(
                f'F.col("{column}").alias("{selected.alias}__{column}")' for column in selected.columns
            )
            lines.append(
                f'{selected.alias} = spark.read.parquet(catalog.get_dataset("{selected.dataset}").path)'
                f".select({columns})"
            )
        for step in ir.steps:
            if isinstance(step, JoinStep):
                lines.append(
                    f"{step.output} = {step.left}.join({step.right}, "
                    f'{self._render_expression(step.condition)}, "{step.how}")'
                )
            elif isinstance(step, FilterStep):
                lines.append(
                    f"{step.output} = {step.input}.filter({self._render_expression(step.predicate)})"
                )
            elif isinstance(step, ProjectStep):
                columns = ", ".join(
                    f'{self._render_expression(item.expression)}.alias("{item.alias}")'
                    for item in step.columns
                )
                lines.append(f"{step.output} = {step.input}.select({columns})")
            elif isinstance(step, AggregateStep):
                groups = ", ".join(
                    f'{self._render_expression(item.expression)}.alias("{item.alias}")'
                    for item in step.group_by
                )
                aggregates = ", ".join(self._render_aggregate(item) for item in step.aggregations)
                lines.append(f"{step.output} = {step.input}.groupBy({groups}).agg({aggregates})")
            elif isinstance(step, SortStep):
                ordering = ", ".join(
                    f"{self._render_expression(item.expression)}.{item.direction}_nulls_{item.nulls}()"
                    for item in step.by
                )
                lines.append(f"{step.output} = {step.input}.orderBy({ordering})")
            elif isinstance(step, LimitStep):
                lines.append(f"{step.output} = {step.input}.limit({step.count})")
            else:
                raise ValueError(f"Unsupported analysis step: {type(step).__name__}")
        lines.append(f"result = {ir.output}")
        return "\n".join(lines)

    def _render_expression(self, expression: Expression) -> str:
        op = expression.op
        args = [self._render_expression(argument) for argument in expression.arguments]
        if op is ExpressionOp.COLUMN:
            return f'F.col("{expression.column}")'
        if op is ExpressionOp.LITERAL:
            return f"F.lit({expression.value!r})"
        symbols = {
            ExpressionOp.EQ: "==",
            ExpressionOp.NE: "!=",
            ExpressionOp.GT: ">",
            ExpressionOp.GTE: ">=",
            ExpressionOp.LT: "<",
            ExpressionOp.LTE: "<=",
            ExpressionOp.AND: "&",
            ExpressionOp.OR: "|",
            ExpressionOp.ADD: "+",
            ExpressionOp.SUBTRACT: "-",
            ExpressionOp.MULTIPLY: "*",
            ExpressionOp.DIVIDE: "/",
        }
        if op in symbols:
            return f"({args[0]} {symbols[op]} {args[1]})"
        if op is ExpressionOp.NOT:
            return f"(~{args[0]})"
        if op is ExpressionOp.IS_NULL:
            return f"{args[0]}.isNull()"
        if op is ExpressionOp.IS_NOT_NULL:
            return f"{args[0]}.isNotNull()"
        if op is ExpressionOp.TO_DATE:
            return f"F.to_date({args[0]})"
        if op is ExpressionOp.DATE_DIFF:
            return f"F.datediff({args[0]}, {args[1]})"
        if op is ExpressionOp.DATE_TRUNC:
            return f"F.date_trunc({expression.value!r}, {args[0]})"
        if op is ExpressionOp.COALESCE:
            return f"F.coalesce({', '.join(args)})"
        if op is ExpressionOp.WHEN:
            return f"F.when({args[0]}, {args[1]}).otherwise({args[2]})"
        raise ValueError(f"Unsupported expression operation: {op}")

    def _render_aggregate(self, aggregate: AggregateExpression) -> str:
        functions = {
            AggregateFunction.COUNT: "count",
            AggregateFunction.COUNT_DISTINCT: "count_distinct",
            AggregateFunction.SUM: "sum",
            AggregateFunction.AVG: "avg",
            AggregateFunction.MIN: "min",
            AggregateFunction.MAX: "max",
        }
        expression = (
            self._render_expression(aggregate.expression) if aggregate.expression is not None else "F.lit(1)"
        )
        return f'F.{functions[aggregate.function]}({expression}).alias("{aggregate.alias}")'

    def _expression(self, expression: Expression) -> Column:
        op = expression.op
        args = [self._expression(argument) for argument in expression.arguments]
        if op is ExpressionOp.COLUMN:
            return F.col(str(expression.column))
        if op is ExpressionOp.LITERAL:
            return F.lit(expression.value)
        binary: dict[ExpressionOp, Callable[[Column, Column], Column]] = {
            ExpressionOp.EQ: lambda left, right: left == right,
            ExpressionOp.NE: lambda left, right: left != right,
            ExpressionOp.GT: lambda left, right: left > right,
            ExpressionOp.GTE: lambda left, right: left >= right,
            ExpressionOp.LT: lambda left, right: left < right,
            ExpressionOp.LTE: lambda left, right: left <= right,
            ExpressionOp.AND: lambda left, right: left & right,
            ExpressionOp.OR: lambda left, right: left | right,
            ExpressionOp.ADD: lambda left, right: left + right,
            ExpressionOp.SUBTRACT: lambda left, right: left - right,
            ExpressionOp.MULTIPLY: lambda left, right: left * right,
            ExpressionOp.DIVIDE: lambda left, right: left / right,
        }
        if op in binary:
            return binary[op](args[0], args[1])
        if op is ExpressionOp.NOT:
            return ~args[0]
        if op is ExpressionOp.IS_NULL:
            return args[0].isNull()
        if op is ExpressionOp.IS_NOT_NULL:
            return args[0].isNotNull()
        if op is ExpressionOp.TO_DATE:
            return F.to_date(args[0])
        if op is ExpressionOp.DATE_DIFF:
            return F.datediff(args[0], args[1])
        if op is ExpressionOp.DATE_TRUNC:
            return F.date_trunc(str(expression.value), args[0])
        if op is ExpressionOp.COALESCE:
            return F.coalesce(*args)
        if op is ExpressionOp.WHEN:
            return F.when(args[0], args[1]).otherwise(args[2])
        raise ValueError(f"Unsupported expression operation: {op}")

    def _aggregate(self, aggregate: AggregateExpression) -> Column:
        expression = self._expression(aggregate.expression) if aggregate.expression is not None else F.lit(1)
        functions = {
            AggregateFunction.COUNT: F.count,
            AggregateFunction.COUNT_DISTINCT: F.count_distinct,
            AggregateFunction.SUM: F.sum,
            AggregateFunction.AVG: F.avg,
            AggregateFunction.MIN: F.min,
            AggregateFunction.MAX: F.max,
        }
        return functions[aggregate.function](expression).alias(aggregate.alias)

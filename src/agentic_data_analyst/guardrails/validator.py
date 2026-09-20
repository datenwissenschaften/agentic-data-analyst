"""Semantic validation and column-lineage checks for the analysis IR."""

from __future__ import annotations

from pathlib import Path

from agentic_data_analyst.catalog.base import Catalog
from agentic_data_analyst.errors import CatalogError
from agentic_data_analyst.models import (
    AggregateStep,
    AnalysisIR,
    Expression,
    ExpressionOp,
    FilterStep,
    JoinStep,
    LimitStep,
    ProjectStep,
    SortStep,
    ValidationIssue,
    ValidationResult,
)


class AnalysisValidator:
    """Validate an IR against catalog authorization and relation lineage."""

    def __init__(
        self,
        catalog: Catalog,
        *,
        approved_data_root: Path,
        max_result_rows: int = 100,
        max_expression_nodes: int = 100,
    ) -> None:
        self._catalog = catalog
        self._approved_root = approved_data_root.resolve()
        self._max_result_rows = max_result_rows
        self._max_expression_nodes = max_expression_nodes

    def validate(self, ir: AnalysisIR) -> ValidationResult:
        issues: list[ValidationIssue] = []
        relations: dict[str, set[str]] = {}

        for index, selected in enumerate(ir.inputs):
            path = f"inputs.{index}"
            if selected.alias in relations:
                issues.append(self._error("duplicate_relation", selected.alias, path))
                continue
            try:
                metadata = self._catalog.get_dataset(selected.dataset)
            except CatalogError:
                issues.append(self._error("unknown_dataset", selected.dataset, path))
                continue
            dataset_path = Path(metadata.path).resolve()
            if not dataset_path.is_relative_to(self._approved_root):
                issues.append(self._error("path_not_approved", metadata.path, path))
            available = {column.name for column in metadata.columns}
            unknown = set(selected.columns) - available
            if unknown:
                issues.append(self._error("unknown_column", ", ".join(sorted(unknown)), f"{path}.columns"))
            relations[selected.alias] = {
                f"{selected.alias}__{column}" for column in selected.columns if column in available
            }

        for index, step in enumerate(ir.steps):
            step_path = f"steps.{index}"
            if step.output in relations:
                issues.append(self._error("duplicate_relation", step.output, f"{step_path}.output"))
                continue
            if isinstance(step, JoinStep):
                left = self._relation(relations, step.left, issues, f"{step_path}.left")
                right = self._relation(relations, step.right, issues, f"{step_path}.right")
                available = left | right
                self._validate_expression(step.condition, available, issues, f"{step_path}.condition")
                self._validate_predicate(step.condition, issues, f"{step_path}.condition")
                relations[step.output] = available
            elif isinstance(step, FilterStep):
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                self._validate_expression(step.predicate, available, issues, f"{step_path}.predicate")
                self._validate_predicate(step.predicate, issues, f"{step_path}.predicate")
                relations[step.output] = available
            elif isinstance(step, ProjectStep):
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                aliases = [column.alias for column in step.columns]
                self._duplicates(aliases, issues, f"{step_path}.columns")
                for column_index, column in enumerate(step.columns):
                    self._validate_expression(
                        column.expression,
                        available,
                        issues,
                        f"{step_path}.columns.{column_index}.expression",
                    )
                relations[step.output] = set(aliases)
            elif isinstance(step, AggregateStep):
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                aliases = [group.alias for group in step.group_by] + [
                    aggregation.alias for aggregation in step.aggregations
                ]
                self._duplicates(aliases, issues, step_path)
                for group_index, group in enumerate(step.group_by):
                    self._validate_expression(
                        group.expression,
                        available,
                        issues,
                        f"{step_path}.group_by.{group_index}.expression",
                    )
                for aggregation_index, aggregation in enumerate(step.aggregations):
                    if aggregation.expression is not None:
                        self._validate_expression(
                            aggregation.expression,
                            available,
                            issues,
                            f"{step_path}.aggregations.{aggregation_index}.expression",
                        )
                relations[step.output] = set(aliases)
            elif isinstance(step, SortStep):
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                for sort_index, sort in enumerate(step.by):
                    self._validate_expression(
                        sort.expression,
                        available,
                        issues,
                        f"{step_path}.by.{sort_index}.expression",
                    )
                relations[step.output] = available
            elif isinstance(step, LimitStep):
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                if step.count > self._max_result_rows:
                    issues.append(
                        self._error(
                            "result_limit_exceeded",
                            f"{step.count} exceeds {self._max_result_rows}",
                            f"{step_path}.count",
                        )
                    )
                relations[step.output] = available

        if ir.output not in relations:
            issues.append(self._error("unknown_output", ir.output, "output"))
        final_step = ir.steps[-1]
        if not isinstance(final_step, LimitStep) or final_step.output != ir.output:
            issues.append(
                self._error(
                    "missing_final_limit",
                    "The output relation must be produced by the final limit step",
                    "output",
                )
            )
        return ValidationResult(is_valid=not issues, issues=tuple(issues))

    def _validate_expression(
        self,
        expression: Expression,
        available: set[str],
        issues: list[ValidationIssue],
        path: str,
    ) -> None:
        nodes = list(self._walk(expression))
        if len(nodes) > self._max_expression_nodes:
            issues.append(self._error("expression_too_complex", str(len(nodes)), path))
        for node in nodes:
            if node.op is ExpressionOp.COLUMN and node.column not in available:
                issues.append(self._error("unknown_column", str(node.column), path))
            if node.op is ExpressionOp.DATE_TRUNC and node.value not in {
                "year",
                "quarter",
                "month",
                "week",
                "day",
                "hour",
            }:
                issues.append(self._error("invalid_date_unit", str(node.value), path))

    @staticmethod
    def _validate_predicate(expression: Expression, issues: list[ValidationIssue], path: str) -> None:
        predicate_ops = {
            ExpressionOp.EQ,
            ExpressionOp.NE,
            ExpressionOp.GT,
            ExpressionOp.GTE,
            ExpressionOp.LT,
            ExpressionOp.LTE,
            ExpressionOp.AND,
            ExpressionOp.OR,
            ExpressionOp.NOT,
            ExpressionOp.IS_NULL,
            ExpressionOp.IS_NOT_NULL,
        }
        if expression.op not in predicate_ops:
            issues.append(
                AnalysisValidator._error(
                    "invalid_predicate", "Filter and join roots must be boolean expressions", path
                )
            )

    @staticmethod
    def _walk(expression: Expression) -> tuple[Expression, ...]:
        descendants = (
            child for argument in expression.arguments for child in AnalysisValidator._walk(argument)
        )
        return (expression, *descendants)

    @staticmethod
    def _relation(
        relations: dict[str, set[str]],
        name: str,
        issues: list[ValidationIssue],
        path: str,
    ) -> set[str]:
        if name not in relations:
            issues.append(AnalysisValidator._error("unknown_relation", name, path))
            return set()
        return relations[name]

    @staticmethod
    def _duplicates(values: list[str], issues: list[ValidationIssue], path: str) -> None:
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            issues.append(AnalysisValidator._error("duplicate_column", ", ".join(duplicates), path))

    @staticmethod
    def _error(code: str, message: str, path: str) -> ValidationIssue:
        return ValidationIssue(severity="error", code=code, message=message, path=path)

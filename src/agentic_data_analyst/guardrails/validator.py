"""Semantic validation and column-lineage checks for the analysis IR."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentic_data_analyst.catalog.base import Catalog
from agentic_data_analyst.errors import CatalogError
from agentic_data_analyst.guardrails.validated import AuthorizedDataset, ValidatedAnalysis
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
from agentic_data_analyst.policy import AnalysisPolicy


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """Public findings plus an internal compile capability when valid."""

    result: ValidationResult
    analysis: ValidatedAnalysis | None


class AnalysisValidator:
    """Validate an IR against catalog authorization, lineage, and resource policy."""

    def __init__(
        self,
        catalog: Catalog,
        *,
        approved_data_root: Path,
        policy: AnalysisPolicy | None = None,
    ) -> None:
        self._catalog = catalog
        self._approved_root = approved_data_root.resolve()
        self._policy = policy or AnalysisPolicy()

    def validate(self, ir: AnalysisIR) -> ValidationResult:
        return self.authorize(ir).result

    def authorize(self, ir: AnalysisIR) -> ValidationOutcome:
        issues: list[ValidationIssue] = []
        relations: dict[str, tuple[str, ...]] = {}
        authorized: list[AuthorizedDataset] = []
        total_expression_nodes = 0
        total_selected_columns = sum(len(selected.columns) for selected in ir.inputs)

        self._limit(len(ir.inputs), self._policy.max_inputs, "too_many_inputs", "inputs", issues)
        self._limit(
            total_selected_columns,
            self._policy.max_total_selected_columns,
            "too_many_selected_columns",
            "inputs",
            issues,
        )
        self._limit(len(ir.steps), self._policy.max_steps, "too_many_steps", "steps", issues)

        for index, selected in enumerate(ir.inputs):
            path = f"inputs.{index}"
            if selected.alias in relations:
                issues.append(self._error("duplicate_relation", selected.alias, path))
                continue
            self._limit(
                len(selected.columns),
                self._policy.max_selected_columns_per_input,
                "too_many_selected_columns",
                f"{path}.columns",
                issues,
            )
            try:
                metadata = self._catalog.get_dataset(selected.dataset)
            except CatalogError:
                issues.append(self._error("unknown_dataset", selected.dataset, path))
                continue
            raw_path = Path(metadata.path)
            if not raw_path.is_absolute():
                issues.append(self._error("path_not_absolute", metadata.path, path))
                continue
            try:
                dataset_path = raw_path.resolve(strict=True)
            except OSError:
                issues.append(self._error("dataset_path_missing", metadata.path, path))
                continue
            if not dataset_path.is_relative_to(self._approved_root):
                issues.append(self._error("path_not_approved", metadata.path, path))
                continue
            catalog_columns = {column.name for column in metadata.columns}
            if len(catalog_columns) != len(metadata.columns):
                issues.append(self._error("duplicate_catalog_column", selected.dataset, path))
            unknown = set(selected.columns) - catalog_columns
            if unknown:
                issues.append(self._error("unknown_column", ", ".join(sorted(unknown)), f"{path}.columns"))
            lineage = tuple(
                f"{selected.alias}__{column}" for column in selected.columns if column in catalog_columns
            )
            relations[selected.alias] = lineage
            authorized.append(
                AuthorizedDataset(
                    dataset=selected.dataset,
                    alias=selected.alias,
                    path=dataset_path,
                    columns=tuple(selected.columns),
                )
            )

        join_count = sum(isinstance(step, JoinStep) for step in ir.steps)
        self._limit(join_count, self._policy.max_joins, "too_many_joins", "steps", issues)
        total_aggregations = sum(
            len(step.aggregations) for step in ir.steps if isinstance(step, AggregateStep)
        )
        self._limit(
            total_aggregations,
            self._policy.max_total_aggregations,
            "too_many_aggregations",
            "steps",
            issues,
        )

        for index, step in enumerate(ir.steps):
            step_path = f"steps.{index}"
            if step.output in relations:
                issues.append(self._error("duplicate_relation", step.output, f"{step_path}.output"))
                continue
            if isinstance(step, JoinStep):
                left = self._relation(relations, step.left, issues, f"{step_path}.left")
                right = self._relation(relations, step.right, issues, f"{step_path}.right")
                if step.left == step.right:
                    issues.append(self._error("self_join_relation", step.left, step_path))
                collisions = set(left) & set(right)
                if collisions:
                    issues.append(
                        self._error("join_column_collision", ", ".join(sorted(collisions)), step_path)
                    )
                available = (*left, *right)
                total_expression_nodes += self._validate_expression(
                    step.condition, set(available), issues, f"{step_path}.condition"
                )
                self._validate_boolean_expression(step.condition, issues, f"{step_path}.condition")
                references = self._column_references(step.condition)
                if left and not references.intersection(left):
                    issues.append(self._error("join_missing_left_reference", step.left, step_path))
                if right and not references.intersection(right):
                    issues.append(self._error("join_missing_right_reference", step.right, step_path))
                relations[step.output] = available
            elif isinstance(step, FilterStep):
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                total_expression_nodes += self._validate_expression(
                    step.predicate, set(available), issues, f"{step_path}.predicate"
                )
                self._validate_boolean_expression(step.predicate, issues, f"{step_path}.predicate")
                relations[step.output] = available
            elif isinstance(step, ProjectStep):
                self._limit(
                    len(step.columns),
                    self._policy.max_project_columns,
                    "too_many_project_columns",
                    f"{step_path}.columns",
                    issues,
                )
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                aliases = [column.alias for column in step.columns]
                self._duplicates(aliases, issues, f"{step_path}.columns")
                for column_index, column in enumerate(step.columns):
                    total_expression_nodes += self._validate_expression(
                        column.expression,
                        set(available),
                        issues,
                        f"{step_path}.columns.{column_index}.expression",
                    )
                relations[step.output] = tuple(aliases)
            elif isinstance(step, AggregateStep):
                self._limit(
                    len(step.group_by),
                    self._policy.max_group_keys,
                    "too_many_group_keys",
                    f"{step_path}.group_by",
                    issues,
                )
                self._limit(
                    len(step.aggregations),
                    self._policy.max_aggregations_per_step,
                    "too_many_aggregations",
                    f"{step_path}.aggregations",
                    issues,
                )
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                aliases = [group.alias for group in step.group_by] + [
                    aggregation.alias for aggregation in step.aggregations
                ]
                self._duplicates(aliases, issues, step_path)
                for group_index, group in enumerate(step.group_by):
                    total_expression_nodes += self._validate_expression(
                        group.expression,
                        set(available),
                        issues,
                        f"{step_path}.group_by.{group_index}.expression",
                    )
                for aggregation_index, aggregation in enumerate(step.aggregations):
                    if aggregation.expression is not None:
                        total_expression_nodes += self._validate_expression(
                            aggregation.expression,
                            set(available),
                            issues,
                            f"{step_path}.aggregations.{aggregation_index}.expression",
                        )
                relations[step.output] = tuple(aliases)
            elif isinstance(step, SortStep):
                self._limit(
                    len(step.by),
                    self._policy.max_sort_keys,
                    "too_many_sort_keys",
                    f"{step_path}.by",
                    issues,
                )
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                for sort_index, sort in enumerate(step.by):
                    total_expression_nodes += self._validate_expression(
                        sort.expression,
                        set(available),
                        issues,
                        f"{step_path}.by.{sort_index}.expression",
                    )
                relations[step.output] = available
            elif isinstance(step, LimitStep):
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                if step.count > self._policy.max_result_rows:
                    issues.append(
                        self._error(
                            "result_limit_exceeded",
                            f"{step.count} exceeds {self._policy.max_result_rows}",
                            f"{step_path}.count",
                        )
                    )
                relations[step.output] = available
            else:
                issues.append(self._error("unsupported_step", type(step).__name__, step_path))

        self._limit(
            total_expression_nodes,
            self._policy.max_total_expression_nodes,
            "too_many_total_expression_nodes",
            "steps",
            issues,
        )
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

        result = ValidationResult(is_valid=not issues, issues=tuple(issues))
        if not result.is_valid:
            return ValidationOutcome(result=result, analysis=None)
        return ValidationOutcome(
            result=result,
            analysis=ValidatedAnalysis(
                ir=ir,
                datasets=tuple(authorized),
                output_columns=relations[ir.output],
            ),
        )

    def _validate_expression(
        self,
        expression: Expression,
        available: set[str],
        issues: list[ValidationIssue],
        path: str,
    ) -> int:
        nodes: list[tuple[Expression, int]] = [(expression, 1)]
        count = 0
        maximum_depth = 0
        while nodes:
            node, depth = nodes.pop()
            count += 1
            maximum_depth = max(maximum_depth, depth)
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
            if node.op is ExpressionOp.WHEN:
                self._validate_boolean_expression(node.arguments[0], issues, f"{path}.when_condition")
            nodes.extend((argument, depth + 1) for argument in node.arguments)
        self._limit(
            count,
            self._policy.max_expression_nodes,
            "expression_too_complex",
            path,
            issues,
        )
        self._limit(
            maximum_depth,
            self._policy.max_expression_depth,
            "expression_too_deep",
            path,
            issues,
        )
        return count

    def _validate_boolean_expression(
        self, expression: Expression, issues: list[ValidationIssue], path: str
    ) -> None:
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
        stack = [expression]
        while stack:
            node = stack.pop()
            if node.op not in predicate_ops:
                issues.append(
                    self._error(
                        "invalid_predicate",
                        "Boolean contexts require comparison, null, or boolean operations",
                        path,
                    )
                )
                return
            if node.op in {ExpressionOp.AND, ExpressionOp.OR, ExpressionOp.NOT}:
                stack.extend(node.arguments)

    @staticmethod
    def _column_references(expression: Expression) -> set[str]:
        references: set[str] = set()
        stack = [expression]
        while stack:
            node = stack.pop()
            if node.op is ExpressionOp.COLUMN and node.column is not None:
                references.add(node.column)
            stack.extend(node.arguments)
        return references

    @staticmethod
    def _relation(
        relations: dict[str, tuple[str, ...]],
        name: str,
        issues: list[ValidationIssue],
        path: str,
    ) -> tuple[str, ...]:
        if name not in relations:
            issues.append(AnalysisValidator._error("unknown_relation", name, path))
            return ()
        return relations[name]

    @staticmethod
    def _duplicates(values: list[str], issues: list[ValidationIssue], path: str) -> None:
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            issues.append(AnalysisValidator._error("duplicate_column", ", ".join(duplicates), path))

    @staticmethod
    def _limit(
        actual: int,
        maximum: int,
        code: str,
        path: str,
        issues: list[ValidationIssue],
    ) -> None:
        if actual > maximum:
            issues.append(
                AnalysisValidator._error(code, f"{actual} exceeds configured maximum {maximum}", path)
            )

    @staticmethod
    def _error(code: str, message: str, path: str) -> ValidationIssue:
        return ValidationIssue(severity="error", code=code, message=message, path=path)

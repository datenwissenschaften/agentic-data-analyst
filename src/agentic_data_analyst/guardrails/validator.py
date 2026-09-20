"""Semantic validation and column-lineage checks for the analysis IR."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from agentic_data_analyst.catalog.base import Catalog
from agentic_data_analyst.errors import CatalogError
from agentic_data_analyst.guardrails.validated import AuthorizedDataset, ValidatedAnalysis
from agentic_data_analyst.models import (
    AggregateFunction,
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


class _ExpressionType(StrEnum):
    BOOLEAN = "boolean"
    NUMBER = "number"
    STRING = "string"
    TEMPORAL = "temporal"
    NULL = "null"
    UNKNOWN = "unknown"


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
        relations: dict[str, dict[str, _ExpressionType]] = {}
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
            except (OSError, RuntimeError, ValueError):
                issues.append(self._error("dataset_path_missing", metadata.path, path))
                continue
            if not dataset_path.is_relative_to(self._approved_root):
                issues.append(self._error("path_not_approved", metadata.path, path))
                continue
            if not (dataset_path.is_file() or dataset_path.is_dir()):
                issues.append(self._error("dataset_path_invalid", metadata.path, path))
                continue
            catalog_columns = {column.name: column for column in metadata.columns}
            if len(catalog_columns) != len(metadata.columns):
                issues.append(self._error("duplicate_catalog_column", selected.dataset, path))
            unknown = set(selected.columns) - set(catalog_columns)
            if unknown:
                issues.append(self._error("unknown_column", ", ".join(sorted(unknown)), f"{path}.columns"))
            lineage = {
                f"{selected.alias}__{column}": self._catalog_type(catalog_columns[column].data_type)
                for column in selected.columns
                if column in catalog_columns
            }
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
                available = {**left, **right}
                expression_nodes, expression_type = self._validate_expression(
                    step.condition, available, issues, f"{step_path}.condition"
                )
                total_expression_nodes += expression_nodes
                self._require_boolean(expression_type, issues, f"{step_path}.condition")
                references = self._column_references(step.condition)
                if left and not references.intersection(left):
                    issues.append(self._error("join_missing_left_reference", step.left, step_path))
                if right and not references.intersection(right):
                    issues.append(self._error("join_missing_right_reference", step.right, step_path))
                relations[step.output] = available
            elif isinstance(step, FilterStep):
                available = self._relation(relations, step.input, issues, f"{step_path}.input")
                expression_nodes, expression_type = self._validate_expression(
                    step.predicate, available, issues, f"{step_path}.predicate"
                )
                total_expression_nodes += expression_nodes
                self._require_boolean(expression_type, issues, f"{step_path}.predicate")
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
                projected: dict[str, _ExpressionType] = {}
                for column_index, column in enumerate(step.columns):
                    expression_nodes, expression_type = self._validate_expression(
                        column.expression,
                        available,
                        issues,
                        f"{step_path}.columns.{column_index}.expression",
                    )
                    total_expression_nodes += expression_nodes
                    projected[column.alias] = expression_type
                relations[step.output] = projected
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
                aggregated: dict[str, _ExpressionType] = {}
                for group_index, group in enumerate(step.group_by):
                    expression_nodes, expression_type = self._validate_expression(
                        group.expression,
                        available,
                        issues,
                        f"{step_path}.group_by.{group_index}.expression",
                    )
                    total_expression_nodes += expression_nodes
                    aggregated[group.alias] = expression_type
                for aggregation_index, aggregation in enumerate(step.aggregations):
                    expression_type = _ExpressionType.NUMBER
                    if aggregation.expression is not None:
                        expression_nodes, expression_type = self._validate_expression(
                            aggregation.expression,
                            available,
                            issues,
                            f"{step_path}.aggregations.{aggregation_index}.expression",
                        )
                        total_expression_nodes += expression_nodes
                    aggregate_path = f"{step_path}.aggregations.{aggregation_index}.expression"
                    if aggregation.function in {AggregateFunction.SUM, AggregateFunction.AVG}:
                        self._require_numeric(expression_type, issues, aggregate_path)
                        expression_type = _ExpressionType.NUMBER
                    elif aggregation.function in {
                        AggregateFunction.COUNT,
                        AggregateFunction.COUNT_DISTINCT,
                    }:
                        expression_type = _ExpressionType.NUMBER
                    elif expression_type not in {
                        _ExpressionType.NUMBER,
                        _ExpressionType.STRING,
                        _ExpressionType.TEMPORAL,
                    }:
                        issues.append(
                            self._error(
                                "invalid_expression_type",
                                f"{aggregation.function} requires a scalar expression",
                                aggregate_path,
                            )
                        )
                    aggregated[aggregation.alias] = expression_type
                relations[step.output] = aggregated
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
                    expression_nodes, _ = self._validate_expression(
                        sort.expression, available, issues, f"{step_path}.by.{sort_index}.expression"
                    )
                    total_expression_nodes += expression_nodes
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
                output_columns=tuple(relations[ir.output]),
            ),
        )

    def _validate_expression(
        self,
        expression: Expression,
        available: dict[str, _ExpressionType],
        issues: list[ValidationIssue],
        path: str,
    ) -> tuple[int, _ExpressionType]:
        nodes: list[tuple[Expression, int]] = [(expression, 1)]
        ordered: list[Expression] = []
        count = 0
        maximum_depth = 0
        while nodes:
            node, depth = nodes.pop()
            ordered.append(node)
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
        inferred: dict[int, _ExpressionType] = {}
        for node in reversed(ordered):
            argument_types = tuple(inferred[id(argument)] for argument in node.arguments)
            inferred[id(node)] = self._infer_expression_type(
                node,
                argument_types,
                available,
                issues,
                path,
            )
        return count, inferred[id(expression)]

    def _infer_expression_type(
        self,
        expression: Expression,
        arguments: tuple[_ExpressionType, ...],
        available: dict[str, _ExpressionType],
        issues: list[ValidationIssue],
        path: str,
    ) -> _ExpressionType:
        op = expression.op
        if op is ExpressionOp.COLUMN:
            return available.get(str(expression.column), _ExpressionType.UNKNOWN)
        if op is ExpressionOp.LITERAL:
            return self._literal_type(expression.value)
        if op in {ExpressionOp.EQ, ExpressionOp.NE}:
            return (
                _ExpressionType.BOOLEAN
                if self._compatible(arguments[0], arguments[1])
                else self._type_error(op, arguments, issues, path)
            )
        if op in {ExpressionOp.GT, ExpressionOp.GTE, ExpressionOp.LT, ExpressionOp.LTE}:
            comparable = {
                _ExpressionType.NUMBER,
                _ExpressionType.STRING,
                _ExpressionType.TEMPORAL,
            }
            if (
                self._compatible(arguments[0], arguments[1])
                and arguments[0] in comparable | {_ExpressionType.NULL}
                and arguments[1] in comparable | {_ExpressionType.NULL}
            ):
                return _ExpressionType.BOOLEAN
            return self._type_error(op, arguments, issues, path)
        if op in {ExpressionOp.AND, ExpressionOp.OR}:
            if all(argument is _ExpressionType.BOOLEAN for argument in arguments):
                return _ExpressionType.BOOLEAN
            return self._type_error(op, arguments, issues, path)
        if op is ExpressionOp.NOT:
            if arguments[0] is _ExpressionType.BOOLEAN:
                return _ExpressionType.BOOLEAN
            return self._type_error(op, arguments, issues, path)
        if op in {
            ExpressionOp.ADD,
            ExpressionOp.SUBTRACT,
            ExpressionOp.MULTIPLY,
            ExpressionOp.DIVIDE,
        }:
            if all(argument is _ExpressionType.NUMBER for argument in arguments):
                return _ExpressionType.NUMBER
            return self._type_error(op, arguments, issues, path)
        if op in {ExpressionOp.IS_NULL, ExpressionOp.IS_NOT_NULL}:
            return _ExpressionType.BOOLEAN
        if op is ExpressionOp.TO_DATE:
            if arguments[0] in {_ExpressionType.STRING, _ExpressionType.TEMPORAL}:
                return _ExpressionType.TEMPORAL
            return self._type_error(op, arguments, issues, path)
        if op is ExpressionOp.DATE_DIFF:
            if all(argument is _ExpressionType.TEMPORAL for argument in arguments):
                return _ExpressionType.NUMBER
            return self._type_error(op, arguments, issues, path)
        if op is ExpressionOp.DATE_TRUNC:
            if arguments[0] is _ExpressionType.TEMPORAL:
                return _ExpressionType.TEMPORAL
            return self._type_error(op, arguments, issues, path)
        if op is ExpressionOp.COALESCE:
            return self._merge_types(op, arguments, issues, path)
        if op is ExpressionOp.WHEN:
            if arguments[0] is not _ExpressionType.BOOLEAN:
                self._type_error(op, arguments[:1], issues, f"{path}.when_condition")
            return self._merge_types(op, arguments[1:], issues, path)
        return self._type_error(op, arguments, issues, path)

    @staticmethod
    def _literal_type(value: object) -> _ExpressionType:
        if value is None:
            return _ExpressionType.NULL
        if isinstance(value, bool):
            return _ExpressionType.BOOLEAN
        if isinstance(value, (int, float)):
            return _ExpressionType.NUMBER
        if isinstance(value, str):
            return _ExpressionType.STRING
        return _ExpressionType.UNKNOWN

    @staticmethod
    def _catalog_type(data_type: str) -> _ExpressionType:
        normalized = data_type.casefold()
        if normalized in {"bool", "boolean"}:
            return _ExpressionType.BOOLEAN
        if normalized.startswith(("int", "uint", "float", "double", "halffloat", "decimal")):
            return _ExpressionType.NUMBER
        if normalized.startswith(("date", "time", "timestamp", "duration")):
            return _ExpressionType.TEMPORAL
        if normalized in {"string", "large_string", "string_view"}:
            return _ExpressionType.STRING
        return _ExpressionType.UNKNOWN

    @staticmethod
    def _compatible(left: _ExpressionType, right: _ExpressionType) -> bool:
        return (
            left is right or left is _ExpressionType.NULL or right is _ExpressionType.NULL
        ) and _ExpressionType.UNKNOWN not in {left, right}

    def _merge_types(
        self,
        op: ExpressionOp,
        arguments: tuple[_ExpressionType, ...],
        issues: list[ValidationIssue],
        path: str,
    ) -> _ExpressionType:
        concrete = [argument for argument in arguments if argument is not _ExpressionType.NULL]
        if not concrete:
            return _ExpressionType.NULL
        first = concrete[0]
        if first is not _ExpressionType.UNKNOWN and all(argument is first for argument in concrete):
            return first
        return self._type_error(op, arguments, issues, path)

    @staticmethod
    def _type_error(
        op: ExpressionOp,
        arguments: tuple[_ExpressionType, ...],
        issues: list[ValidationIssue],
        path: str,
    ) -> _ExpressionType:
        actual = ", ".join(argument.value for argument in arguments)
        issues.append(
            AnalysisValidator._error(
                "invalid_expression_type",
                f"{op} does not support operand types: {actual}",
                path,
            )
        )
        return _ExpressionType.UNKNOWN

    @staticmethod
    def _require_boolean(
        expression_type: _ExpressionType,
        issues: list[ValidationIssue],
        path: str,
    ) -> None:
        if expression_type is not _ExpressionType.BOOLEAN:
            issues.append(
                AnalysisValidator._error(
                    "invalid_predicate",
                    "Boolean context requires a boolean expression",
                    path,
                )
            )

    @staticmethod
    def _require_numeric(
        expression_type: _ExpressionType,
        issues: list[ValidationIssue],
        path: str,
    ) -> None:
        if expression_type is not _ExpressionType.NUMBER:
            issues.append(
                AnalysisValidator._error(
                    "invalid_expression_type",
                    "Aggregate requires a numeric expression",
                    path,
                )
            )

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
        relations: dict[str, dict[str, _ExpressionType]],
        name: str,
        issues: list[ValidationIssue],
        path: str,
    ) -> dict[str, _ExpressionType]:
        if name not in relations:
            issues.append(AnalysisValidator._error("unknown_relation", name, path))
            return {}
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

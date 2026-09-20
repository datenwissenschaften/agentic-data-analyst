"""Typed contracts shared by workflow stages."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

type Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]
type Scalar = str | int | float | bool | None
type ResultValue = Scalar


class StrictModel(BaseModel):
    """Base contract that rejects unexpected LLM-provided fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ColumnMetadata(StrictModel):
    name: Identifier
    data_type: str
    description: str = ""
    nullable: bool = True


class RelationshipMetadata(StrictModel):
    source_column: Identifier
    target_dataset: Identifier
    target_column: Identifier
    relationship: Literal["many_to_one", "one_to_many", "one_to_one"] = "many_to_one"


class DatasetMetadata(StrictModel):
    name: Identifier
    description: str
    path: str
    columns: tuple[ColumnMetadata, ...]
    relationships: tuple[RelationshipMetadata, ...] = ()
    tags: tuple[str, ...] = ()


class CatalogCandidate(StrictModel):
    """Small discovery response; schemas are loaded only after selection."""

    name: Identifier
    description: str
    tags: tuple[str, ...] = ()
    score: float = 0.0


class AnalyticsQuestion(StrictModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2_000)]


class DiscoverySelection(StrictModel):
    datasets: tuple[Identifier, ...] = Field(min_length=1, max_length=8)
    rationale: str

    @model_validator(mode="after")
    def unique_datasets(self) -> DiscoverySelection:
        if len(set(self.datasets)) != len(self.datasets):
            raise ValueError("datasets must be unique")
        return self


class DatasetSelection(StrictModel):
    dataset: Identifier
    alias: Identifier
    columns: tuple[Identifier, ...] = Field(min_length=1)
    rationale: str

    @model_validator(mode="after")
    def unique_columns(self) -> DatasetSelection:
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("selected columns must be unique")
        return self


class AnalysisPlan(StrictModel):
    objective: str
    datasets: tuple[DatasetSelection, ...] = Field(min_length=1)
    steps: tuple[str, ...] = Field(min_length=1, max_length=20)
    result_grain: str
    expected_columns: tuple[Identifier, ...] = Field(min_length=1)
    assumptions: tuple[str, ...] = ()


class ExpressionOp(StrEnum):
    COLUMN = "column"
    LITERAL = "literal"
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    AND = "and"
    OR = "or"
    NOT = "not"
    ADD = "add"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"
    TO_DATE = "to_date"
    DATE_DIFF = "date_diff"
    DATE_TRUNC = "date_trunc"
    COALESCE = "coalesce"
    WHEN = "when"


class Expression(StrictModel):
    """Closed expression tree compiled to Spark Columns."""

    op: ExpressionOp
    column: Identifier | None = None
    value: Scalar = None
    arguments: tuple[Expression, ...] = ()

    @model_validator(mode="after")
    def check_shape(self) -> Expression:
        arity: dict[ExpressionOp, tuple[int, int]] = {
            ExpressionOp.COLUMN: (0, 0),
            ExpressionOp.LITERAL: (0, 0),
            ExpressionOp.NOT: (1, 1),
            ExpressionOp.IS_NULL: (1, 1),
            ExpressionOp.IS_NOT_NULL: (1, 1),
            ExpressionOp.TO_DATE: (1, 1),
            ExpressionOp.EQ: (2, 2),
            ExpressionOp.NE: (2, 2),
            ExpressionOp.GT: (2, 2),
            ExpressionOp.GTE: (2, 2),
            ExpressionOp.LT: (2, 2),
            ExpressionOp.LTE: (2, 2),
            ExpressionOp.AND: (2, 2),
            ExpressionOp.OR: (2, 2),
            ExpressionOp.ADD: (2, 2),
            ExpressionOp.SUBTRACT: (2, 2),
            ExpressionOp.MULTIPLY: (2, 2),
            ExpressionOp.DIVIDE: (2, 2),
            ExpressionOp.DATE_DIFF: (2, 2),
            ExpressionOp.DATE_TRUNC: (1, 1),
            ExpressionOp.COALESCE: (1, 20),
            ExpressionOp.WHEN: (3, 3),
        }
        lower, upper = arity[self.op]
        if not lower <= len(self.arguments) <= upper:
            raise ValueError(f"{self.op} requires {lower}..{upper} arguments")
        if self.op is ExpressionOp.COLUMN and self.column is None:
            raise ValueError("column expressions require 'column'")
        if self.op is not ExpressionOp.COLUMN and self.column is not None:
            raise ValueError("only column expressions may set 'column'")
        if self.op is ExpressionOp.DATE_TRUNC and not isinstance(self.value, str):
            raise ValueError("date_trunc requires a string unit in 'value'")
        return self


class NamedExpression(StrictModel):
    alias: Identifier
    expression: Expression


class AggregateFunction(StrEnum):
    COUNT = "count"
    COUNT_DISTINCT = "count_distinct"
    SUM = "sum"
    AVG = "avg"
    MIN = "min"
    MAX = "max"


class AggregateExpression(StrictModel):
    alias: Identifier
    function: AggregateFunction
    expression: Expression | None = None

    @model_validator(mode="after")
    def require_aggregate_input(self) -> AggregateExpression:
        if self.function is not AggregateFunction.COUNT and self.expression is None:
            raise ValueError(f"{self.function} requires an expression")
        return self


class JoinStep(StrictModel):
    type: Literal["join"] = "join"
    output: Identifier
    left: Identifier
    right: Identifier
    condition: Expression
    how: Literal["inner", "left", "right", "full"] = "inner"


class FilterStep(StrictModel):
    type: Literal["filter"] = "filter"
    output: Identifier
    input: Identifier
    predicate: Expression


class ProjectStep(StrictModel):
    type: Literal["project"] = "project"
    output: Identifier
    input: Identifier
    columns: tuple[NamedExpression, ...] = Field(min_length=1)


class AggregateStep(StrictModel):
    type: Literal["aggregate"] = "aggregate"
    output: Identifier
    input: Identifier
    group_by: tuple[NamedExpression, ...] = ()
    aggregations: tuple[AggregateExpression, ...] = Field(min_length=1)


class SortExpression(StrictModel):
    expression: Expression
    direction: Literal["asc", "desc"] = "asc"
    nulls: Literal["first", "last"] = "last"


class SortStep(StrictModel):
    type: Literal["sort"] = "sort"
    output: Identifier
    input: Identifier
    by: tuple[SortExpression, ...] = Field(min_length=1)


class LimitStep(StrictModel):
    type: Literal["limit"] = "limit"
    output: Identifier
    input: Identifier
    count: int = Field(gt=0, le=10_000)


type AnalysisStep = Annotated[
    JoinStep | FilterStep | ProjectStep | AggregateStep | SortStep | LimitStep,
    Field(discriminator="type"),
]


class AnalysisIR(StrictModel):
    version: Literal["1"] = "1"
    inputs: tuple[DatasetSelection, ...] = Field(min_length=1, max_length=8)
    steps: tuple[AnalysisStep, ...] = Field(min_length=1, max_length=30)
    output: Identifier


class GeneratedAnalysis(StrictModel):
    dialect: Literal["spark_dataframe_ir/v1"] = "spark_dataframe_ir/v1"
    ir: AnalysisIR
    pyspark_preview: str


class ValidationIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    path: str | None = None


class ValidationResult(StrictModel):
    is_valid: bool
    issues: tuple[ValidationIssue, ...] = ()


class ExecutionResult(StrictModel):
    columns: tuple[str, ...]
    rows: tuple[dict[str, ResultValue], ...]
    row_count: int
    truncated: bool
    duration_ms: int


class ResultExplanation(StrictModel):
    summary: str


class AnalysisResponse(StrictModel):
    question: str
    plan: AnalysisPlan
    datasets_used: tuple[str, ...]
    generated_analysis: GeneratedAnalysis
    validation: ValidationResult
    result: ExecutionResult
    explanation: str | None = None
    stage_durations_ms: dict[str, int] = Field(default_factory=dict)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

from pathlib import Path
from typing import Any

import pytest

from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.guardrails import AnalysisValidator
from agentic_data_analyst.models import (
    AnalysisIR,
    CatalogCandidate,
    ColumnMetadata,
    DatasetMetadata,
    DatasetSelection,
    Expression,
    ExpressionOp,
    FilterStep,
    JoinStep,
    LimitStep,
    NamedExpression,
    ProjectStep,
    SortExpression,
    SortStep,
)
from agentic_data_analyst.policy import AnalysisPolicy


class StaticCatalog:
    def __init__(self, metadata: DatasetMetadata) -> None:
        self.metadata = metadata

    def list_datasets(self) -> tuple[CatalogCandidate, ...]:
        return ()

    def search(self, query: str, *, limit: int = 5) -> tuple[CatalogCandidate, ...]:
        return ()

    def get_dataset(self, name: str) -> DatasetMetadata:
        return self.metadata


def _path_ir() -> AnalysisIR:
    return AnalysisIR(
        inputs=(
            DatasetSelection(
                dataset="players",
                alias="p",
                columns=("player_id",),
                rationale="identifier",
            ),
        ),
        steps=(LimitStep(output="result", input="p", count=1),),
        output="result",
    )


def _metadata(path: Path | str) -> DatasetMetadata:
    return DatasetMetadata(
        name="players",
        description="players",
        path=str(path),
        columns=(ColumnMetadata(name="player_id", data_type="string"),),
    )


def test_validator_accepts_bounded_known_lineage(
    catalog: LocalParquetCatalog, sample_data_dir: Path, analysis_ir: AnalysisIR
) -> None:
    result = AnalysisValidator(catalog, approved_data_root=sample_data_dir).validate(analysis_ir)

    assert result.is_valid
    assert result.issues == ()


def test_validator_rejects_unknown_column_and_missing_final_limit(
    catalog: LocalParquetCatalog, sample_data_dir: Path, analysis_ir: AnalysisIR
) -> None:
    invalid = analysis_ir.model_copy(
        update={
            "steps": (
                FilterStep(
                    output="filtered",
                    input="p",
                    predicate=Expression(op=ExpressionOp.COLUMN, column="p__password"),
                ),
            ),
            "output": "filtered",
        }
    )

    result = AnalysisValidator(catalog, approved_data_root=sample_data_dir).validate(invalid)

    assert not result.is_valid
    assert {issue.code for issue in result.issues} == {
        "unknown_column",
        "invalid_predicate",
        "missing_final_limit",
    }


def test_ir_schema_rejects_arbitrary_operations() -> None:
    payload = {
        "version": "1",
        "inputs": [],
        "steps": [{"type": "python", "code": "import os; os.environ"}],
        "output": "result",
    }

    try:
        AnalysisIR.model_validate(payload)
    except ValueError as exc:
        assert "union_tag_invalid" in str(exc) or "at least 1" in str(exc)
    else:
        raise AssertionError("Arbitrary Python operation was accepted")


@pytest.mark.parametrize(
    ("policy_override", "expected_code"),
    [
        ({"max_inputs": 1}, "too_many_inputs"),
        ({"max_selected_columns_per_input": 1}, "too_many_selected_columns"),
        ({"max_total_selected_columns": 3}, "too_many_selected_columns"),
        ({"max_steps": 3}, "too_many_steps"),
        ({"max_aggregations_per_step": 1}, "too_many_aggregations"),
        ({"max_total_aggregations": 1}, "too_many_aggregations"),
        ({"max_expression_depth": 1}, "expression_too_deep"),
        ({"max_expression_nodes": 2}, "expression_too_complex"),
        ({"max_total_expression_nodes": 5}, "too_many_total_expression_nodes"),
        ({"max_result_rows": 5}, "result_limit_exceeded"),
    ],
)
def test_central_policy_limits_are_enforced(
    policy_override: dict[str, Any],
    expected_code: str,
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
    analysis_ir: AnalysisIR,
) -> None:
    policy = AnalysisPolicy(**policy_override)

    result = AnalysisValidator(catalog, approved_data_root=sample_data_dir, policy=policy).validate(
        analysis_ir
    )

    assert expected_code in {issue.code for issue in result.issues}


def test_boolean_operators_reject_non_boolean_children(
    catalog: LocalParquetCatalog, sample_data_dir: Path, analysis_ir: AnalysisIR
) -> None:
    invalid_predicate = Expression(
        op=ExpressionOp.AND,
        arguments=(
            Expression(op=ExpressionOp.COLUMN, column="p__player_id"),
            Expression(op=ExpressionOp.LITERAL, value=True),
        ),
    )
    invalid = analysis_ir.model_copy(
        update={
            "steps": (
                FilterStep(output="filtered", input="p", predicate=invalid_predicate),
                LimitStep(output="result", input="filtered", count=1),
            )
        }
    )

    result = AnalysisValidator(catalog, approved_data_root=sample_data_dir).validate(invalid)

    assert "invalid_predicate" in {issue.code for issue in result.issues}


def test_join_condition_must_reference_both_relations(
    catalog: LocalParquetCatalog, sample_data_dir: Path, analysis_ir: AnalysisIR
) -> None:
    join = analysis_ir.steps[0]
    one_sided = join.model_copy(
        update={
            "condition": Expression(
                op=ExpressionOp.EQ,
                arguments=(
                    Expression(op=ExpressionOp.COLUMN, column="p__player_id"),
                    Expression(op=ExpressionOp.COLUMN, column="p__player_id"),
                ),
            )
        }
    )
    invalid = analysis_ir.model_copy(update={"steps": (one_sided, *analysis_ir.steps[1:])})

    result = AnalysisValidator(catalog, approved_data_root=sample_data_dir).validate(invalid)

    assert "join_missing_right_reference" in {issue.code for issue in result.issues}


def test_relational_operation_limits_are_enforced(
    catalog: LocalParquetCatalog, sample_data_dir: Path, analysis_ir: AnalysisIR
) -> None:
    join = analysis_ir.steps[0]
    assert isinstance(join, JoinStep)
    extra_join = join.model_copy(update={"output": "joined_again", "left": "joined"})
    aggregate = analysis_ir.steps[1]
    aggregate = aggregate.model_copy(
        update={
            "input": "joined_again",
            "group_by": (
                *aggregate.group_by,
                NamedExpression(
                    alias="segment_copy",
                    expression=Expression(op=ExpressionOp.COLUMN, column="p__segment"),
                ),
            ),
        }
    )
    sort = analysis_ir.steps[2]
    assert isinstance(sort, SortStep)
    sort = sort.model_copy(update={"by": (*sort.by, SortExpression(expression=sort.by[0].expression))})
    excessive = analysis_ir.model_copy(
        update={"steps": (join, extra_join, aggregate, sort, analysis_ir.steps[-1])}
    )

    result = AnalysisValidator(
        catalog,
        approved_data_root=sample_data_dir,
        policy=AnalysisPolicy(max_joins=1, max_group_keys=1, max_sort_keys=1),
    ).validate(excessive)

    codes = {issue.code for issue in result.issues}
    assert {"too_many_joins", "too_many_group_keys", "too_many_sort_keys"} <= codes


def test_project_column_limit_is_enforced(catalog: LocalParquetCatalog, sample_data_dir: Path) -> None:
    column = Expression(op=ExpressionOp.COLUMN, column="p__player_id")
    ir = _path_ir().model_copy(
        update={
            "steps": (
                ProjectStep(
                    output="projected",
                    input="p",
                    columns=(
                        NamedExpression(alias="first", expression=column),
                        NamedExpression(alias="second", expression=column),
                    ),
                ),
                LimitStep(output="result", input="projected", count=1),
            )
        }
    )

    result = AnalysisValidator(
        catalog,
        approved_data_root=sample_data_dir,
        policy=AnalysisPolicy(max_project_columns=1),
    ).validate(ir)

    assert "too_many_project_columns" in {issue.code for issue in result.issues}


def test_path_validation_uses_canonical_containment(tmp_path: Path) -> None:
    root = tmp_path / "data"
    nested = root / "nested"
    nested.mkdir(parents=True)
    approved = nested / "players.parquet"
    approved.touch()
    outside = tmp_path / "outside.parquet"
    outside.touch()
    similar_prefix = tmp_path / "data-other" / "players.parquet"
    similar_prefix.parent.mkdir()
    similar_prefix.touch()
    symlink = root / "linked.parquet"
    symlink.symlink_to(outside)
    traversal = nested / ".." / ".." / "outside.parquet"

    valid = AnalysisValidator(StaticCatalog(_metadata(approved)), approved_data_root=root).validate(
        _path_ir()
    )
    assert valid.is_valid

    cases = (
        (_metadata(outside), "path_not_approved"),
        (_metadata(similar_prefix), "path_not_approved"),
        (_metadata(symlink), "path_not_approved"),
        (_metadata(traversal), "path_not_approved"),
        (_metadata(root / "missing.parquet"), "dataset_path_missing"),
        (_metadata("relative.parquet"), "path_not_absolute"),
    )
    for metadata, expected_code in cases:
        result = AnalysisValidator(StaticCatalog(metadata), approved_data_root=root).validate(_path_ir())
        assert expected_code in {issue.code for issue in result.issues}

from pathlib import Path

from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.guardrails import AnalysisValidator
from agentic_data_analyst.models import AnalysisIR, Expression, ExpressionOp, FilterStep


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

from pathlib import Path

from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.execution import SparkAnalysisRunner, SparkCompiler, SparkSessionFactory
from agentic_data_analyst.guardrails import AnalysisValidator
from agentic_data_analyst.models import AnalysisIR


def test_compiler_renders_reviewable_pyspark_preview(
    catalog: LocalParquetCatalog, analysis_ir: AnalysisIR
) -> None:
    preview = SparkCompiler(catalog).render(analysis_ir)

    assert 'spark.read.parquet(catalog.get_dataset("players").path)' in preview
    assert ".groupBy(" in preview
    assert ".agg(" in preview
    assert "exec(" not in preview


def test_runner_executes_compiled_dataframe_operations(
    catalog: LocalParquetCatalog,
    sample_data_dir: Path,
    spark_sessions: SparkSessionFactory,
    analysis_ir: AnalysisIR,
) -> None:
    validator = AnalysisValidator(catalog, approved_data_root=sample_data_dir)
    runner = SparkAnalysisRunner(
        validator=validator,
        compiler=SparkCompiler(catalog),
        session_factory=spark_sessions,
    )

    result = runner.execute(analysis_ir)

    assert result.columns == ("segment", "average_duration", "session_count")
    assert {row["segment"] for row in result.rows} == {"casual", "core", "competitive"}
    assert all(float(row["average_duration"]) > 0 for row in result.rows)

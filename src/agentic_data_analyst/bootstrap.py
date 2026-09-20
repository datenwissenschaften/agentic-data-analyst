"""Application composition root."""

from agentic_data_analyst.agents import (
    GenerationAgent,
    InterpretationAgent,
    MetadataDiscoveryAgent,
    PlanningAgent,
)
from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.config import Settings
from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.execution import SparkAnalysisRunner, SparkCompiler, SparkSessionFactory
from agentic_data_analyst.guardrails import AnalysisValidator
from agentic_data_analyst.llm.openrouter import OpenRouterClient
from agentic_data_analyst.workflow import AnalysisWorkflow


def build_workflow(settings: Settings) -> AnalysisWorkflow:
    """Wire production adapters at one explicit composition boundary."""
    if settings.openrouter_api_key is None:
        raise LLMError("OPENROUTER_API_KEY is required for the production workflow")
    catalog = LocalParquetCatalog(settings.catalog_path)
    llm = OpenRouterClient(
        api_key=settings.openrouter_api_key,
        model=settings.openrouter_model,
        base_url=settings.openrouter_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    validator = AnalysisValidator(
        catalog,
        approved_data_root=settings.catalog_path,
        max_result_rows=settings.max_result_rows,
    )
    compiler = SparkCompiler(catalog)
    runner = SparkAnalysisRunner(
        validator=validator,
        compiler=compiler,
        session_factory=SparkSessionFactory(master=settings.spark_master),
        max_result_rows=settings.max_result_rows,
    )
    return AnalysisWorkflow(
        catalog=catalog,
        discovery=MetadataDiscoveryAgent(llm),
        planner=PlanningAgent(llm),
        generator=GenerationAgent(llm),
        validator=validator,
        compiler=compiler,
        runner=runner,
        interpreter=InterpretationAgent(llm),
        max_result_rows=settings.max_result_rows,
    )

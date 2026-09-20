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
    policy = settings.analysis_policy
    catalog = LocalParquetCatalog(settings.catalog_path)
    llm = OpenRouterClient(
        api_key=settings.openrouter_api_key.get_secret_value(),
        model=settings.openrouter_model,
        base_url=str(settings.openrouter_base_url),
        timeout_seconds=settings.llm_timeout_seconds,
        max_response_bytes=settings.max_llm_response_bytes,
    )
    validator = AnalysisValidator(
        catalog,
        approved_data_root=settings.catalog_path,
        policy=policy,
    )
    compiler = SparkCompiler()
    runner = SparkAnalysisRunner(
        validator=validator,
        compiler=compiler,
        session_factory=SparkSessionFactory(master=settings.spark_master),
        execution_timeout_seconds=settings.execution_timeout_seconds,
    )
    return AnalysisWorkflow(
        catalog=catalog,
        discovery=MetadataDiscoveryAgent(llm, max_attempts=settings.llm_max_attempts),
        planner=PlanningAgent(llm, max_attempts=settings.llm_max_attempts),
        generator=GenerationAgent(llm, max_attempts=settings.llm_max_attempts),
        validator=validator,
        compiler=compiler,
        runner=runner,
        interpreter=InterpretationAgent(llm, max_attempts=settings.llm_max_attempts),
        policy=policy,
    )

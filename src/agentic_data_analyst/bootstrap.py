"""Application composition root."""

from agentic_data_analyst.agents import (
    GenerationAgent,
    InterpretationAgent,
    MetadataDiscoveryAgent,
    PlanningAgent,
)
from agentic_data_analyst.catalog.base import Catalog
from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.config import Settings
from agentic_data_analyst.dbt import DbtArtifactLoader, DbtEnrichedCatalog
from agentic_data_analyst.errors import LLMError
from agentic_data_analyst.execution import SparkAnalysisRunner, SparkCompiler, SparkSessionFactory
from agentic_data_analyst.guardrails import AnalysisValidator
from agentic_data_analyst.llm.openrouter import OpenRouterClient
from agentic_data_analyst.workflow import AnalysisWorkflow


def build_catalog(settings: Settings) -> Catalog:
    """Build the physical catalog, optionally enriched with dbt metadata.

    dbt enrichment is opt-in: it only activates when `DBT_PROJECT_PATH` points
    at a directory containing dbt's compiled artifacts. Enrichment never
    changes which datasets are selectable or how their physical paths are
    authorized; see `agentic_data_analyst.dbt.catalog` for the boundary.
    """
    catalog: Catalog = LocalParquetCatalog(settings.catalog_path)
    if settings.dbt_project_path is not None:
        project = DbtArtifactLoader(settings.dbt_project_path).load()
        catalog = DbtEnrichedCatalog(catalog, project)
    return catalog


def build_workflow(settings: Settings) -> AnalysisWorkflow:
    """Wire production adapters at one explicit composition boundary."""
    if settings.openrouter_api_key is None:
        raise LLMError("OPENROUTER_API_KEY is required for the production workflow")
    policy = settings.analysis_policy
    catalog = build_catalog(settings)
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

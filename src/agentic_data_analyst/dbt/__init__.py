"""dbt metadata integration: parse dbt artifacts and enrich catalog discovery.

This package never invokes dbt-core and never requires a running dbt process.
It reads `manifest.json` (required) and `catalog.json` (optional) from a dbt
project's `target/` directory, normalizes the subset of their documented
schema this project understands, and enriches an existing `Catalog`
implementation with the result. See `catalog.py` for the security boundary
this enrichment preserves.
"""

from agentic_data_analyst.dbt.catalog import DbtEnrichedCatalog
from agentic_data_analyst.dbt.lineage import DirectLineage, build_direct_lineage, direct_edges, label
from agentic_data_analyst.dbt.loader import DbtArtifactLoader, DbtColumn, DbtProject, DbtRelation, DbtTest

__all__ = [
    "DbtArtifactLoader",
    "DbtColumn",
    "DbtEnrichedCatalog",
    "DbtProject",
    "DbtRelation",
    "DbtTest",
    "DirectLineage",
    "build_direct_lineage",
    "direct_edges",
    "label",
]

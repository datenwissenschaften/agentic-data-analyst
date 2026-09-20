"""Dataset catalog abstractions."""

from agentic_data_analyst.catalog.base import Catalog
from agentic_data_analyst.catalog.local import LocalParquetCatalog

__all__ = ["Catalog", "LocalParquetCatalog"]

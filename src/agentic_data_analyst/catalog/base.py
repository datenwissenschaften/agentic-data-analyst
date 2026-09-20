"""Catalog provider contract."""

from __future__ import annotations

from typing import Protocol

from agentic_data_analyst.models import CatalogCandidate, DatasetMetadata


class Catalog(Protocol):
    """Interface implemented by local and future enterprise catalogs."""

    def list_datasets(self) -> tuple[CatalogCandidate, ...]: ...

    def search(self, query: str, *, limit: int = 5) -> tuple[CatalogCandidate, ...]: ...

    def get_dataset(self, name: str) -> DatasetMetadata: ...

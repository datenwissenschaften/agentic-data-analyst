"""Filesystem-backed Parquet catalog."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds
from pydantic import BaseModel, ConfigDict, ValidationError

from agentic_data_analyst.errors import CatalogError
from agentic_data_analyst.models import (
    CatalogCandidate,
    ColumnMetadata,
    DatasetMetadata,
    RelationshipMetadata,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class _ColumnAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = ""


class _DatasetAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    columns: dict[str, _ColumnAnnotation] = {}
    relationships: tuple[RelationshipMetadata, ...] = ()
    tags: tuple[str, ...] = ()


class LocalParquetCatalog:
    """Discover Parquet datasets and enrich them with optional sidecar metadata."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._datasets = self._discover()

    @property
    def root(self) -> Path:
        return self._root

    def refresh(self) -> None:
        self._datasets = self._discover()

    def list_datasets(self) -> tuple[CatalogCandidate, ...]:
        return tuple(
            CatalogCandidate(name=item.name, description=item.description, tags=item.tags)
            for item in sorted(self._datasets.values(), key=lambda dataset: dataset.name)
        )

    def search(self, query: str, *, limit: int = 5) -> tuple[CatalogCandidate, ...]:
        if limit < 1:
            return ()
        query_terms = set(_TOKEN_RE.findall(query.lower()))
        ranked: list[CatalogCandidate] = []
        for dataset in self._datasets.values():
            name_terms = set(_TOKEN_RE.findall(dataset.name.lower().replace("_", " ")))
            body = " ".join(
                [dataset.description, *dataset.tags, *(column.name for column in dataset.columns)]
            ).lower()
            body_terms = set(_TOKEN_RE.findall(body))
            score = float(4 * len(query_terms & name_terms) + len(query_terms & body_terms))
            if score > 0 or not query_terms:
                ranked.append(
                    CatalogCandidate(
                        name=dataset.name,
                        description=dataset.description,
                        tags=dataset.tags,
                        score=score,
                    )
                )
        ranked.sort(key=lambda candidate: (-candidate.score, candidate.name))
        return tuple(ranked[:limit])

    def get_dataset(self, name: str) -> DatasetMetadata:
        try:
            return self._datasets[name]
        except KeyError as exc:
            raise CatalogError(f"Unknown dataset: {name}") from exc

    def _discover(self) -> dict[str, DatasetMetadata]:
        if not self._root.exists():
            raise CatalogError(f"Catalog path does not exist: {self._root}")
        datasets: dict[str, DatasetMetadata] = {}
        for parquet_path in sorted(self._root.glob("*.parquet")):
            name = parquet_path.stem
            annotation = self._read_annotation(name)
            try:
                schema = ds.dataset(parquet_path, format="parquet").schema
            except Exception as exc:
                raise CatalogError(f"Cannot read Parquet schema for {name}") from exc
            columns = tuple(
                ColumnMetadata(
                    name=field.name,
                    data_type=str(field.type),
                    nullable=field.nullable,
                    description=(annotation.columns.get(field.name, _ColumnAnnotation()).description),
                )
                for field in schema
            )
            datasets[name] = DatasetMetadata(
                name=name,
                description=annotation.description,
                path=str(parquet_path.resolve()),
                columns=columns,
                relationships=annotation.relationships,
                tags=annotation.tags,
            )
        if not datasets:
            raise CatalogError(
                f"No '*.parquet' datasets found under {self._root}. Run 'agentic-data-generate'."
            )
        return datasets

    def _read_annotation(self, name: str) -> _DatasetAnnotation:
        path = self._root / f"{name}.metadata.json"
        if not path.exists():
            return _DatasetAnnotation(description=f"Parquet dataset '{name}'")
        try:
            raw: Any = json.loads(path.read_text(encoding="utf-8"))
            return _DatasetAnnotation.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise CatalogError(f"Invalid metadata sidecar: {path}") from exc

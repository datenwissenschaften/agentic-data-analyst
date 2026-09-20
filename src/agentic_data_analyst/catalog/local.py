"""Filesystem-backed Parquet catalog."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentic_data_analyst.errors import CatalogError
from agentic_data_analyst.models import (
    CatalogCandidate,
    ColumnMetadata,
    DatasetMetadata,
    RelationshipMetadata,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MAX_METADATA_BYTES = 1_000_000
_MAX_SEARCH_CHARS = 2_000
_MAX_SEARCH_RESULTS = 100


class _ColumnAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = ""


class _DatasetAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    columns: dict[str, _ColumnAnnotation] = Field(default_factory=dict)
    relationships: tuple[RelationshipMetadata, ...] = ()
    tags: tuple[str, ...] = ()


class LocalParquetCatalog:
    """Discover Parquet datasets and enrich them with optional sidecar metadata."""

    def __init__(self, root: Path) -> None:
        try:
            self._root = root.resolve(strict=True)
        except OSError as exc:
            raise CatalogError(f"Catalog path does not exist: {root}") from exc
        if not self._root.is_dir():
            raise CatalogError(f"Catalog path is not a directory: {self._root}")
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
        if len(query) > _MAX_SEARCH_CHARS:
            raise CatalogError(f"Catalog query exceeds {_MAX_SEARCH_CHARS} characters")
        limit = min(limit, _MAX_SEARCH_RESULTS)
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
            dataset = self._datasets[name]
        except KeyError as exc:
            raise CatalogError(f"Unknown dataset: {name}") from exc
        if not Path(dataset.path).exists():
            raise CatalogError(f"Dataset path no longer exists: {name}")
        return dataset

    def _discover(self) -> dict[str, DatasetMetadata]:
        datasets: dict[str, DatasetMetadata] = {}
        casefold_names: dict[str, str] = {}
        for parquet_path in self._parquet_paths():
            name = parquet_path.stem
            try:
                canonical_path = parquet_path.resolve(strict=True)
            except OSError as exc:
                raise CatalogError(f"Cannot resolve Parquet dataset: {parquet_path}") from exc
            if not canonical_path.is_relative_to(self._root):
                raise CatalogError(f"Parquet dataset resolves outside catalog root: {parquet_path}")
            folded = name.casefold()
            if folded in casefold_names:
                raise CatalogError(
                    f"Duplicate dataset name '{name}' conflicts with '{casefold_names[folded]}'"
                )
            casefold_names[folded] = name
            annotation = self._read_annotation(parquet_path)
            try:
                schema = ds.dataset(canonical_path, format="parquet").schema
            except Exception as exc:
                raise CatalogError(f"Cannot read Parquet schema for {name}") from exc
            schema_names = schema.names
            if len(set(schema_names)) != len(schema_names):
                raise CatalogError(f"Duplicate columns in Parquet schema for {name}")
            unknown_annotations = set(annotation.columns) - set(schema_names)
            if unknown_annotations:
                raise CatalogError(
                    f"Metadata for {name} describes unknown columns: {sorted(unknown_annotations)}"
                )
            columns = tuple(
                ColumnMetadata(
                    name=field.name,
                    data_type=str(field.type),
                    nullable=field.nullable,
                    description=(annotation.columns.get(field.name, _ColumnAnnotation()).description),
                )
                for field in schema
            )
            try:
                datasets[name] = DatasetMetadata(
                    name=name,
                    description=annotation.description,
                    path=str(canonical_path),
                    columns=columns,
                    relationships=annotation.relationships,
                    tags=annotation.tags,
                )
            except ValidationError as exc:
                raise CatalogError(f"Invalid dataset metadata for {name}") from exc
        if not datasets:
            raise CatalogError(
                f"No '*.parquet' datasets found under {self._root}. Run 'agentic-data-generate'."
            )
        self._validate_relationships(datasets)
        return datasets

    def _parquet_paths(self) -> tuple[Path, ...]:
        paths = []
        for path in self._root.rglob("*.parquet"):
            relative = path.relative_to(self._root)
            if any(parent.suffix == ".parquet" for parent in relative.parents):
                continue
            paths.append(path)
        return tuple(sorted(paths))

    def _read_annotation(self, parquet_path: Path) -> _DatasetAnnotation:
        path = parquet_path.with_suffix(".metadata.json")
        if not path.exists():
            return _DatasetAnnotation(description=f"Parquet dataset '{parquet_path.stem}'")
        try:
            canonical_path = path.resolve(strict=True)
            if not canonical_path.is_relative_to(self._root):
                raise CatalogError(f"Metadata sidecar resolves outside catalog root: {path}")
            if canonical_path.stat().st_size > _MAX_METADATA_BYTES:
                raise CatalogError(f"Metadata sidecar exceeds {_MAX_METADATA_BYTES} bytes: {path}")
            raw: Any = json.loads(canonical_path.read_text(encoding="utf-8"))
            return _DatasetAnnotation.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise CatalogError(f"Invalid metadata sidecar: {path}") from exc

    @staticmethod
    def _validate_relationships(datasets: dict[str, DatasetMetadata]) -> None:
        for dataset in datasets.values():
            source_columns = {column.name for column in dataset.columns}
            for relationship in dataset.relationships:
                if relationship.source_column not in source_columns:
                    raise CatalogError(
                        f"Relationship on {dataset.name} references unknown source column "
                        f"{relationship.source_column}"
                    )
                target = datasets.get(relationship.target_dataset)
                if target is None:
                    raise CatalogError(
                        f"Relationship on {dataset.name} references unknown dataset "
                        f"{relationship.target_dataset}"
                    )
                target_columns = {column.name for column in target.columns}
                if relationship.target_column not in target_columns:
                    raise CatalogError(
                        f"Relationship from {dataset.name} references unknown target column "
                        f"{relationship.target_dataset}.{relationship.target_column}"
                    )

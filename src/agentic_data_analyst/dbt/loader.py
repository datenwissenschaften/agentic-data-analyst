"""Path-safe loading and normalization of dbt manifest/catalog artifacts.

This module never invokes dbt-core and never requires a running dbt process: it
only parses artifacts dbt itself already writes to a project's `target/`
directory (`manifest.json`, optionally `catalog.json`). Supported artifact
schema versions are declared explicitly in `_SUPPORTED_MANIFEST_VERSIONS` and
`_SUPPORTED_CATALOG_VERSIONS`; anything else fails closed with `DbtArtifactError`
rather than being silently reinterpreted.

Tested against dbt manifest schema versions v11 and v12 (dbt-core 1.7-1.9) and
catalog schema version v1.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ValidationError

from agentic_data_analyst.dbt.schema import (
    DbtCatalog,
    DbtCatalogEntry,
    DbtColumnNode,
    DbtManifest,
    DbtNode,
    DbtSource,
)
from agentic_data_analyst.errors import DbtArtifactError

_MAX_ARTIFACT_BYTES = 25_000_000
_MAX_NODES = 5_000
_MAX_TEXT_FIELD_CHARS = 50_000

_SUPPORTED_MANIFEST_VERSIONS = re.compile(r"^https://schemas\.getdbt\.com/dbt/manifest/v(11|12)\.json$")
_SUPPORTED_CATALOG_VERSIONS = re.compile(r"^https://schemas\.getdbt\.com/dbt/catalog/v1\.json$")

_SUPPORTED_TEST_TYPES = frozenset({"not_null", "unique", "relationships", "accepted_values"})
_REF_PATTERN = re.compile(r"ref\(\s*['\"]([A-Za-z0-9_]+)['\"]\s*\)")


@dataclass(frozen=True, slots=True)
class DbtColumn:
    name: str
    description: str
    declared_data_type: str | None


@dataclass(frozen=True, slots=True)
class DbtRelation:
    unique_id: str
    kind: str  # "model" or "source"
    name: str
    database: str | None
    schema_name: str | None
    identifier: str
    description: str
    columns: tuple[DbtColumn, ...]
    tags: tuple[str, ...]
    depends_on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DbtTest:
    unique_id: str
    test_type: str
    depends_on: tuple[str, ...]
    columns: tuple[str, ...]
    target_ref: str | None
    accepted_values: tuple[object, ...]


@dataclass(frozen=True, slots=True)
class DbtProject:
    """Normalized, agent-safe view of a dbt project's compiled artifacts."""

    manifest_schema_version: str
    catalog_schema_version: str | None
    relations: dict[str, DbtRelation] = field(default_factory=dict)
    tests: tuple[DbtTest, ...] = ()

    def relation(self, unique_id: str) -> DbtRelation | None:
        return self.relations.get(unique_id)


class DbtArtifactLoader:
    """Load `manifest.json` (required) and `catalog.json` (optional) from one project root."""

    def __init__(
        self,
        project_root: Path,
        *,
        manifest_filename: str = "manifest.json",
        catalog_filename: str = "catalog.json",
    ) -> None:
        try:
            self._root = project_root.resolve(strict=True)
        except OSError as exc:
            raise DbtArtifactError(f"dbt artifact directory does not exist: {project_root}") from exc
        if not self._root.is_dir():
            raise DbtArtifactError(f"dbt artifact path is not a directory: {self._root}")
        self._manifest_filename = manifest_filename
        self._catalog_filename = catalog_filename

    def load(self) -> DbtProject:
        manifest = self._parse(DbtManifest, self._read_json(self._manifest_filename, required=True))
        if not _SUPPORTED_MANIFEST_VERSIONS.match(manifest.metadata.dbt_schema_version):
            raise DbtArtifactError(
                "Unsupported dbt manifest schema version: "
                f"{manifest.metadata.dbt_schema_version!r}. Supported: manifest v11, v12."
            )

        catalog_raw = self._read_json(self._catalog_filename, required=False)
        catalog = self._parse(DbtCatalog, catalog_raw) if catalog_raw is not None else None
        catalog_version: str | None = None
        if catalog is not None:
            if not _SUPPORTED_CATALOG_VERSIONS.match(catalog.metadata.dbt_schema_version):
                raise DbtArtifactError(
                    f"Unsupported dbt catalog schema version: {catalog.metadata.dbt_schema_version!r}. "
                    "Supported: catalog v1."
                )
            catalog_version = catalog.metadata.dbt_schema_version

        total_nodes = len(manifest.nodes) + len(manifest.sources)
        if total_nodes > _MAX_NODES:
            raise DbtArtifactError(f"dbt manifest exceeds the supported node count ({total_nodes} > {_MAX_NODES})")

        catalog_columns = self._catalog_column_types(catalog)
        relations: dict[str, DbtRelation] = {}
        tests: list[DbtTest] = []

        for unique_id, source in manifest.sources.items():
            if source.resource_type != "source":
                raise DbtArtifactError(f"Unexpected resource_type for manifest source {unique_id!r}")
            relations[unique_id] = self._normalize_source(unique_id, source, catalog_columns.get(unique_id, {}))

        for unique_id, node in manifest.nodes.items():
            if node.resource_type == "model":
                relations[unique_id] = self._normalize_model(unique_id, node, catalog_columns.get(unique_id, {}))
            elif node.resource_type == "test":
                test = self._normalize_test(unique_id, node)
                if test is not None:
                    tests.append(test)
            # Other resource types (seed, snapshot, analysis, macro-backed nodes, ...) carry no
            # semantic metadata this integration surfaces; they are read and dropped, never
            # reinterpreted.

        return DbtProject(
            manifest_schema_version=manifest.metadata.dbt_schema_version,
            catalog_schema_version=catalog_version,
            relations=relations,
            tests=tuple(sorted(tests, key=lambda test: test.unique_id)),
        )

    def _read_json(self, filename: str, *, required: bool) -> object | None:
        path = self._root / filename
        try:
            canonical = path.resolve(strict=True)
        except OSError:
            if required:
                raise DbtArtifactError(f"Missing required dbt artifact: {path}") from None
            return None
        if not canonical.is_relative_to(self._root):
            raise DbtArtifactError(f"dbt artifact resolves outside its project root: {path}")
        if not canonical.is_file():
            raise DbtArtifactError(f"dbt artifact is not a regular file: {path}")
        size = canonical.stat().st_size
        if size > _MAX_ARTIFACT_BYTES:
            raise DbtArtifactError(f"dbt artifact exceeds {_MAX_ARTIFACT_BYTES} bytes: {path}")
        try:
            parsed: object = json.loads(canonical.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise DbtArtifactError(f"Malformed dbt artifact JSON: {path}") from exc
        return parsed

    @staticmethod
    def _parse[T: BaseModel](model: type[T], raw: object) -> T:
        try:
            return model.model_validate(raw)
        except ValidationError as exc:
            raise DbtArtifactError(f"dbt artifact does not match the supported {model.__name__} shape") from exc

    def _catalog_column_types(self, catalog: DbtCatalog | None) -> dict[str, dict[str, str]]:
        if catalog is None:
            return {}
        merged: dict[str, DbtCatalogEntry] = {**catalog.sources, **catalog.nodes}
        return {
            unique_id: {name: column.type for name, column in entry.columns.items()}
            for unique_id, entry in merged.items()
        }

    def _normalize_model(self, unique_id: str, node: DbtNode, catalog_types: dict[str, str]) -> DbtRelation:
        identifier = node.alias or self._relation_identifier(node.relation_name) or node.name
        return DbtRelation(
            unique_id=unique_id,
            kind="model",
            name=node.name,
            database=node.database,
            schema_name=node.schema_,
            identifier=identifier,
            description=self._clip(node.description),
            columns=self._columns(node.columns, catalog_types),
            tags=self._clip_tuple(node.tags),
            depends_on=tuple(node.depends_on.nodes),
        )

    def _normalize_source(self, unique_id: str, source: DbtSource, catalog_types: dict[str, str]) -> DbtRelation:
        identifier = source.identifier or self._relation_identifier(source.relation_name) or source.name
        return DbtRelation(
            unique_id=unique_id,
            kind="source",
            name=source.name,
            database=source.database,
            schema_name=source.schema_,
            identifier=identifier,
            description=self._clip(source.description),
            columns=self._columns(source.columns, catalog_types),
            tags=self._clip_tuple(source.tags),
            depends_on=(),
        )

    def _normalize_test(self, unique_id: str, node: DbtNode) -> DbtTest | None:
        if node.test_metadata is None:
            return None
        test_type = node.test_metadata.name
        if test_type not in _SUPPORTED_TEST_TYPES:
            return None
        kwargs = node.test_metadata.test_kwargs
        columns = (kwargs.column_name,) if kwargs.column_name else ()
        target_ref = None
        if kwargs.to:
            match = _REF_PATTERN.search(kwargs.to)
            target_ref = match.group(1) if match else kwargs.to
        return DbtTest(
            unique_id=unique_id,
            test_type=test_type,
            depends_on=tuple(node.depends_on.nodes),
            columns=columns,
            target_ref=target_ref,
            accepted_values=tuple(kwargs.values[:100]),
        )

    def _columns(self, raw_columns: dict[str, DbtColumnNode], catalog_types: dict[str, str]) -> tuple[DbtColumn, ...]:
        columns = [
            DbtColumn(
                name=name,
                description=self._clip(raw.description),
                declared_data_type=self._clip(declared)
                if (declared := (catalog_types.get(name) or raw.data_type))
                else None,
            )
            for name, raw in raw_columns.items()
        ]
        return tuple(sorted(columns, key=lambda column: column.name))

    @staticmethod
    def _relation_identifier(relation_name: str | None) -> str | None:
        if not relation_name:
            return None
        # relation_name is a quoted "database"."schema"."identifier" string; the identifier
        # is the last dotted, possibly quoted, segment.
        last = relation_name.rsplit(".", 1)[-1]
        return last.strip('"').strip("`")

    @staticmethod
    def _clip(value: str) -> str:
        return value if len(value) <= _MAX_TEXT_FIELD_CHARS else value[:_MAX_TEXT_FIELD_CHARS]

    @staticmethod
    def _clip_tuple(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(DbtArtifactLoader._clip(value) for value in values)

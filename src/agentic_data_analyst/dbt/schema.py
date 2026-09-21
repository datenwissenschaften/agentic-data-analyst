"""Typed models for the subset of the dbt manifest/catalog artifact schemas we consume.

These models mirror dbt's documented artifact JSON structures
(https://schemas.getdbt.com/dbt/manifest/<version>.json and
.../catalog/<version>.json) closely enough to extract semantic metadata, without
depending on dbt-core at runtime. They intentionally ignore fields the agent does
not use (macros, exposures, metrics, compiled SQL, timing, ...): dbt manifests
carry hundreds of fields, and copying all of them into the agent's trust boundary
would blur the line between "documented metadata we understand" and "opaque
structure we would otherwise have to reinterpret". `extra="ignore"` here only
means unused *raw* fields are dropped during parsing; every field the loader
does use is declared explicitly, and unknown *shapes* for those fields (wrong
types, missing schema version) still fail parsing.

Supported artifact schema versions are declared in `loader.py`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _LenientModel(BaseModel):
    """Base for raw dbt artifact parsing: tolerate unknown fields, ignore them."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class DbtArtifactMetadata(_LenientModel):
    dbt_schema_version: str
    dbt_version: str | None = None
    generated_at: str | None = None
    project_name: str | None = None


class DbtColumnNode(_LenientModel):
    name: str
    description: str = ""
    data_type: str | None = None
    tags: tuple[str, ...] = ()


class DbtDependsOn(_LenientModel):
    nodes: tuple[str, ...] = ()
    macros: tuple[str, ...] = ()


class DbtTestMetadataKwargs(_LenientModel):
    column_name: str | None = None
    to: str | None = None
    field: str | None = None
    values: tuple[object, ...] = ()


class DbtTestMetadata(_LenientModel):
    name: str
    test_kwargs: DbtTestMetadataKwargs = Field(default_factory=DbtTestMetadataKwargs, alias="kwargs")

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class DbtNode(_LenientModel):
    """A manifest node: models, seeds, snapshots, and generic tests share this shape."""

    unique_id: str
    resource_type: str
    name: str
    description: str = ""
    database: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    alias: str | None = None
    relation_name: str | None = None
    columns: dict[str, DbtColumnNode] = Field(default_factory=dict)
    tags: tuple[str, ...] = ()
    depends_on: DbtDependsOn = DbtDependsOn()
    test_metadata: DbtTestMetadata | None = None

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class DbtSource(_LenientModel):
    unique_id: str
    resource_type: str = "source"
    source_name: str
    name: str
    identifier: str | None = None
    description: str = ""
    database: str | None = None
    schema_: str | None = Field(default=None, alias="schema")
    relation_name: str | None = None
    columns: dict[str, DbtColumnNode] = Field(default_factory=dict)
    tags: tuple[str, ...] = ()

    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class DbtManifest(_LenientModel):
    metadata: DbtArtifactMetadata
    nodes: dict[str, DbtNode] = Field(default_factory=dict)
    sources: dict[str, DbtSource] = Field(default_factory=dict)


class DbtCatalogColumn(_LenientModel):
    type: str
    name: str | None = None
    comment: str | None = None


class DbtCatalogEntry(_LenientModel):
    columns: dict[str, DbtCatalogColumn] = Field(default_factory=dict)


class DbtCatalog(_LenientModel):
    metadata: DbtArtifactMetadata
    nodes: dict[str, DbtCatalogEntry] = Field(default_factory=dict)
    sources: dict[str, DbtCatalogEntry] = Field(default_factory=dict)

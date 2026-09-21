"""Enrich a physical catalog with dbt-sourced semantic metadata.

`DbtEnrichedCatalog` wraps an existing `Catalog` implementation; it never
replaces it. Every dataset it can return still comes from the wrapped
catalog's own `get_dataset`/`list_datasets`, which still performs its own path
authorization; this module only adds descriptive fields (`relation`,
`lineage`, `quality_expectations`, `metadata_source`, `external_id`, and
per-column `declared_data_type`) and a lexical search-ranking boost.

Security boundary: dbt models with no matching physical dataset (for example
downstream marts that were never materialized as Parquet, such as this
project's synthetic `mart_player_retention`) are never returned as selectable
`CatalogCandidate`/`DatasetMetadata` objects — only their *text* contributes to
the search-ranking boost of datasets that do have physical backing. A
dataset's presence in dbt's dependency graph never grants it a path, and
`AnalysisValidator` re-authorizes every dataset from the physical catalog
independently of anything this module attaches. All dbt-sourced text
(descriptions, tags, test targets, accepted values) flows through the same
`StrictModel` fields, size limits, and "untrusted data" prompt framing as
existing catalog metadata — see `agents/planning.py` — so it can never become
an instruction, a path, or an executable expression.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from agentic_data_analyst.catalog.base import Catalog
from agentic_data_analyst.dbt.lineage import DirectLineage, build_direct_lineage, label
from agentic_data_analyst.dbt.loader import DbtProject, DbtRelation, DbtTest
from agentic_data_analyst.errors import CatalogError
from agentic_data_analyst.models import (
    CatalogCandidate,
    DatasetMetadata,
    LineageMetadata,
    QualityExpectationMetadata,
    RelationMetadata,
    Scalar,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_NAME_WEIGHT = 4
_DBT_WEIGHT = 2
_MAX_SEARCH_RESULTS = 100


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def _coerce_scalar(value: object) -> Scalar:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)  # a list/dict/etc in test kwargs is malformed; keep it visible, never structural


class DbtEnrichedCatalog:
    """A `Catalog` that annotates a physical catalog's datasets with dbt metadata."""

    def __init__(self, base: Catalog, project: DbtProject) -> None:
        self._base = base
        self._project = project
        self._lineage = build_direct_lineage(project)
        self._match: dict[str, str] = self._match_physical_datasets(base, project)
        self._connected_text: dict[str, str] = self._build_connected_text()

    def list_datasets(self) -> tuple[CatalogCandidate, ...]:
        return tuple(self._enrich_candidate(candidate) for candidate in self._base.list_datasets())

    def search(self, query: str, *, limit: int = 5) -> tuple[CatalogCandidate, ...]:
        if limit < 1:
            return ()
        limit = min(limit, _MAX_SEARCH_RESULTS)
        query_terms = _tokens(query)
        scored: list[tuple[float, CatalogCandidate]] = []
        for candidate in self._base.list_datasets():
            score = self._score(candidate.name, query_terms)
            if score > 0 or not query_terms:
                scored.append((score, self._enrich_candidate(candidate, score=score)))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return tuple(candidate for _, candidate in scored[:limit])

    def get_dataset(self, name: str) -> DatasetMetadata:
        metadata = self._base.get_dataset(name)
        unique_id = self._match.get(name)
        if unique_id is None:
            return metadata
        relation = self._project.relation(unique_id)
        if relation is None:  # pragma: no cover - defensive; _match only points at known relations
            raise CatalogError(f"dbt relation match for {name!r} is no longer present")
        lineage = self._lineage.get(unique_id, DirectLineage(upstream=(), downstream=()))
        declared_types = {
            column.name: column.declared_data_type for column in relation.columns if column.declared_data_type
        }
        columns = tuple(
            column.model_copy(update={"declared_data_type": declared_types[column.name]})
            if column.name in declared_types
            else column
            for column in metadata.columns
        )
        return metadata.model_copy(
            update={
                "columns": columns,
                "metadata_source": "dbt",
                "external_id": relation.unique_id,
                "relation": RelationMetadata(
                    database=relation.database,
                    schema_name=relation.schema_name,
                    identifier=relation.identifier,
                ),
                "lineage": LineageMetadata(upstream=lineage.upstream, downstream=lineage.downstream),
                "quality_expectations": self._quality_expectations(
                    unique_id, {column.name for column in metadata.columns}
                ),
            }
        )

    @property
    def dbt_project(self) -> DbtProject:
        """The parsed dbt project, for lineage visualization outside the catalog protocol."""
        return self._project

    def dataset_dbt_relation(self, name: str) -> DbtRelation | None:
        """The dbt relation matched to a physical dataset name, if any."""
        unique_id = self._match.get(name)
        return None if unique_id is None else self._project.relation(unique_id)

    def _enrich_candidate(self, candidate: CatalogCandidate, *, score: float | None = None) -> CatalogCandidate:
        unique_id = self._match.get(candidate.name)
        if unique_id is None:
            return candidate if score is None else candidate.model_copy(update={"score": score})
        lineage = self._lineage.get(unique_id, DirectLineage(upstream=(), downstream=()))
        update: dict[str, object] = {
            "lineage": LineageMetadata(upstream=lineage.upstream, downstream=lineage.downstream)
        }
        if score is not None:
            update["score"] = score
        return candidate.model_copy(update=update)

    def _score(self, dataset_name: str, query_terms: set[str]) -> float:
        if not query_terms:
            return 0.0
        try:
            metadata = self._base.get_dataset(dataset_name)
        except CatalogError:
            return 0.0
        name_terms = _tokens(dataset_name.replace("_", " "))
        body = " ".join([metadata.description, *metadata.tags, *(column.name for column in metadata.columns)])
        body_terms = _tokens(body)
        base_score = float(_NAME_WEIGHT * len(query_terms & name_terms) + len(query_terms & body_terms))
        dbt_terms = _tokens(self._connected_text.get(dataset_name, ""))
        dbt_score = float(_DBT_WEIGHT * len(query_terms & dbt_terms))
        return base_score + dbt_score

    def _build_connected_text(self) -> dict[str, str]:
        """For each matched physical dataset, the description/tag/column text of dbt nodes
        directly connected to it (itself plus direct upstream and downstream), used only to
        widen search recall — never returned to a caller as dataset content."""
        text: dict[str, str] = {}
        for dataset_name, unique_id in self._match.items():
            relation = self._project.relation(unique_id)
            if relation is None:
                continue
            connected_ids = {unique_id, *relation.depends_on}
            connected_ids.update(
                other_id for other_id, other in self._project.relations.items() if unique_id in other.depends_on
            )
            fragments: list[str] = []
            for connected_id in connected_ids:
                connected = self._project.relation(connected_id)
                if connected is None:
                    continue
                fragments.append(connected.name)
                fragments.append(connected.description)
                fragments.extend(connected.tags)
                fragments.extend(column.name for column in connected.columns)
                fragments.extend(column.description for column in connected.columns)
            text[dataset_name] = " ".join(fragments)
        return text

    def _quality_expectations(self, unique_id: str, known_columns: set[str]) -> tuple[QualityExpectationMetadata, ...]:
        expectations: list[QualityExpectationMetadata] = []
        for test in self._project.tests:
            if not test.depends_on or test.depends_on[0] != unique_id:
                continue
            expectation = self._to_quality_expectation(test, known_columns)
            if expectation is not None:
                expectations.append(expectation)
        return tuple(expectations)

    @staticmethod
    def _to_quality_expectation(test: DbtTest, known_columns: set[str]) -> QualityExpectationMetadata | None:
        columns = tuple(column for column in test.columns if column in known_columns)
        if test.columns and not columns:
            return None  # the test targets a column this catalog snapshot no longer has
        try:
            return QualityExpectationMetadata(
                unique_id=test.unique_id,
                test_type=test.test_type,  # type: ignore[arg-type]
                columns=columns,
                target=test.target_ref,
                accepted_values=tuple(_coerce_scalar(value) for value in test.accepted_values),
            )
        except ValueError:
            return None  # malformed/oversized test metadata is dropped defensively, not raised

    @staticmethod
    def _match_physical_datasets(base: Catalog, project: DbtProject) -> dict[str, str]:
        kind_priority = {"model": 0, "source": 1}
        by_identifier: dict[str, list[DbtRelation]] = {}
        for relation in project.relations.values():
            by_identifier.setdefault(relation.identifier.casefold(), []).append(relation)
        match: dict[str, str] = {}
        for candidate in base.list_datasets():
            options = by_identifier.get(candidate.name.casefold())
            if not options:
                continue
            best = min(options, key=lambda relation: (kind_priority.get(relation.kind, 99), relation.unique_id))
            match[candidate.name] = best.unique_id
        return match


def dbt_lineage_labels(project: DbtProject) -> Mapping[str, str]:
    """Map every relation's unique_id to its display label, for visualization callers."""
    return {unique_id: label(relation) for unique_id, relation in project.relations.items()}

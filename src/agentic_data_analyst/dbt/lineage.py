"""Deterministic lineage derivation from a parsed dbt project.

Only direct edges are represented. Downstream lineage is the reverse of the
declared `depends_on` upstream graph — it is derived, never invented — and a
reference to a unique_id absent from the project (a pruned or disabled node,
or a malformed manifest edge) is skipped rather than raised: an incomplete
edge is a normal shape for a partially-selected dbt run, not evidence of a
corrupt artifact. Self-references are dropped so accidental or malicious
self-cycles cannot loop; because only direct edges are computed (no
transitive closure), general cycles between two or more nodes cannot cause
unbounded traversal either.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentic_data_analyst.dbt.loader import DbtProject, DbtRelation


def label(relation: DbtRelation) -> str:
    """A short, human-readable, collision-resistant lineage node label."""
    return f"{relation.kind}:{relation.name}"


@dataclass(frozen=True, slots=True)
class DirectLineage:
    upstream: tuple[str, ...]
    downstream: tuple[str, ...]


def build_direct_lineage(project: DbtProject) -> dict[str, DirectLineage]:
    """Map each relation's unique_id to its direct upstream/downstream labels."""
    upstream: dict[str, set[str]] = {unique_id: set() for unique_id in project.relations}
    downstream: dict[str, set[str]] = {unique_id: set() for unique_id in project.relations}
    for unique_id, relation in project.relations.items():
        for dependency_id in relation.depends_on:
            if dependency_id == unique_id:
                continue
            dependency = project.relations.get(dependency_id)
            if dependency is None:
                continue
            upstream[unique_id].add(label(dependency))
            downstream[dependency_id].add(label(relation))
    return {
        unique_id: DirectLineage(
            upstream=tuple(sorted(upstream[unique_id])), downstream=tuple(sorted(downstream[unique_id]))
        )
        for unique_id in project.relations
    }


def direct_edges(project: DbtProject) -> tuple[tuple[str, str], ...]:
    """All direct (upstream_label, downstream_label) edges, for lineage visualization only.

    This is presentation data. It is never consulted by discovery, planning, or
    validation, so a malformed or adversarial edge here can misdraw a diagram
    but cannot influence dataset selection or execution.
    """
    edges: set[tuple[str, str]] = set()
    for unique_id, relation in project.relations.items():
        for dependency_id in relation.depends_on:
            if dependency_id == unique_id:
                continue
            dependency = project.relations.get(dependency_id)
            if dependency is None:
                continue
            edges.add((label(dependency), label(relation)))
    return tuple(sorted(edges))

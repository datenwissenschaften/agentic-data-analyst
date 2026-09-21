"""Regenerate the synthetic manifest.json / catalog.json committed in target/.

These artifacts are hand-specified here (not produced by a real `dbt parse` /
`dbt docs generate` run) so the agentic-data-analyst example works without
installing dbt-core or a warehouse. They are written to match the documented
shape of dbt's manifest v12 and catalog v1 artifact schemas closely enough for
`agentic_data_analyst.dbt.DbtArtifactLoader` to parse them; they are not a
full, dbt-validated manifest/catalog dump.

Run with: python examples/dbt/gaming_analytics/generate_artifacts.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PROJECT = "gaming_analytics"
GENERATED_AT = "2025-06-01T00:00:00.000000Z"
DBT_VERSION = "1.8.5"


def source_id(table: str) -> str:
    return f"source.{PROJECT}.raw.{table}"


def model_id(name: str) -> str:
    return f"model.{PROJECT}.{name}"


def test_id(name: str) -> str:
    return f"test.{PROJECT}.{name}"


def column(name: str, description: str) -> dict[str, Any]:
    return {"name": name, "description": description, "data_type": None, "tags": []}


SOURCES: dict[str, dict[str, Any]] = {
    source_id("raw_players"): {
        "unique_id": source_id("raw_players"),
        "resource_type": "source",
        "source_name": "raw",
        "name": "raw_players",
        "identifier": "players",
        "database": "analytics",
        "schema": "raw",
        "relation_name": '"analytics"."raw"."players"',
        "description": "Raw player account, acquisition, geography, and behavioral segment attributes.",
        "tags": ["raw", "player"],
        "columns": {
            "player_id": column("player_id", "Stable synthetic player identifier."),
            "signup_at": column("signup_at", "UTC account creation time."),
            "segment": column("segment", "Behavioral segment assigned at signup."),
            "region": column("region", "Synthetic player region."),
            "acquisition_channel": column("acquisition_channel", "Channel credited with acquisition."),
        },
    },
    source_id("raw_sessions"): {
        "unique_id": source_id("raw_sessions"),
        "resource_type": "source",
        "source_name": "raw",
        "name": "raw_sessions",
        "identifier": "sessions",
        "database": "analytics",
        "schema": "raw",
        "relation_name": '"analytics"."raw"."sessions"',
        "description": "Raw player login sessions with duration and device context.",
        "tags": ["raw", "session"],
        "columns": {
            "session_id": column("session_id", "Stable synthetic session identifier."),
            "player_id": column("player_id", "Player that opened the session."),
            "session_start": column("session_start", "UTC session start time."),
        },
    },
    source_id("raw_events"): {
        "unique_id": source_id("raw_events"),
        "resource_type": "source",
        "source_name": "raw",
        "name": "raw_events",
        "identifier": "events",
        "database": "analytics",
        "schema": "raw",
        "relation_name": '"analytics"."raw"."events"',
        "description": "Raw product telemetry events emitted during player sessions.",
        "tags": ["raw", "event"],
        "columns": {
            "event_id": column("event_id", "Stable synthetic event identifier."),
            "session_id": column("session_id", "Session containing the event."),
        },
    },
}


def model(
    name: str,
    *,
    alias: str,
    schema: str,
    description: str,
    tags: list[str],
    depends_on: list[str],
    columns: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "unique_id": model_id(name),
        "resource_type": "model",
        "name": name,
        "alias": alias,
        "database": "analytics",
        "schema": schema,
        "relation_name": f'"analytics"."{schema}"."{alias}"',
        "description": description,
        "tags": tags,
        "columns": columns,
        "depends_on": {"nodes": depends_on, "macros": []},
    }


MODELS: dict[str, dict[str, Any]] = {
    model_id("stg_players"): model(
        "stg_players",
        alias="players",
        schema="staging",
        description=(
            "Cleaned, one-row-per-player staging model built directly from the raw player "
            "source. Curated entry point other models join against for player attributes."
        ),
        tags=["staging", "player"],
        depends_on=[source_id("raw_players")],
        columns={
            "player_id": column("player_id", "Stable synthetic player identifier."),
            "signup_at": column("signup_at", "UTC account creation time."),
            "segment": column("segment", "Behavioral segment assigned at signup."),
            "region": column("region", "Synthetic player region."),
            "acquisition_channel": column("acquisition_channel", "Channel credited with acquisition."),
        },
    ),
    model_id("stg_sessions"): model(
        "stg_sessions",
        alias="sessions",
        schema="staging",
        description="Cleaned player session staging model built directly from the raw session source.",
        tags=["staging", "session"],
        depends_on=[source_id("raw_sessions")],
        columns={
            "session_id": column("session_id", "Stable synthetic session identifier."),
            "player_id": column("player_id", "Player that opened the session."),
            "session_start": column("session_start", "UTC session start time."),
            "session_end": column("session_end", "UTC session end time."),
            "duration_minutes": column("duration_minutes", "Session length in minutes."),
            "device": column("device", "Device family used for the session."),
        },
    ),
    model_id("fct_player_sessions"): model(
        "fct_player_sessions",
        alias="fct_player_sessions",
        schema="marts",
        description=(
            "Session-level fact table joining player attributes with session engagement "
            "metrics, including a derived retained_7d flag (whether the session occurred at "
            "least 7 days after the player's signup) used to compute mart_player_retention."
        ),
        tags=["marts", "fact", "retention"],
        depends_on=[model_id("stg_sessions"), model_id("stg_players"), source_id("raw_events")],
        columns={
            "session_id": column("session_id", "Stable synthetic session identifier."),
            "player_id": column("player_id", "Player represented by this session row."),
            "segment": column("segment", "Behavioral segment (casual, core, or competitive)."),
            "region": column("region", "Synthetic player region."),
            "session_start": column("session_start", "UTC session start time."),
            "signup_at": column("signup_at", "UTC account creation time."),
            "retained_7d": column(
                "retained_7d", "True when this session occurred 7 or more days after the player's signup."
            ),
            "event_count": column("event_count", "Telemetry events recorded during this session."),
        },
    ),
    model_id("mart_player_retention"): model(
        "mart_player_retention",
        alias="mart_player_retention",
        schema="marts",
        description=(
            "Weekly 7-day player retention rate by segment and region, aggregated from "
            "fct_player_sessions. retention_7d is the share of a cohort's sessions that "
            "occurred 7 or more days after signup; player_count is the distinct player count "
            "backing that rate. A declining retention_7d for a segment/region/cohort "
            "combination is the primary signal analysts use this mart to investigate."
        ),
        tags=["marts", "retention"],
        depends_on=[model_id("fct_player_sessions")],
        columns={
            "segment": column("segment", "Behavioral segment (casual, core, or competitive)."),
            "region": column("region", "Synthetic player region."),
            "cohort_week": column("cohort_week", "Week-truncated signup date defining the cohort."),
            "retention_7d": column("retention_7d", "Share of the cohort's sessions retained at 7 or more days."),
            "player_count": column("player_count", "Distinct players backing the retention_7d estimate."),
        },
    ),
}


def test_node(
    name: str,
    *,
    test_name: str,
    depends_on: list[str],
    column_name: str | None = None,
    to: str | None = None,
    field: str | None = None,
    values: list[str] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if column_name is not None:
        kwargs["column_name"] = column_name
    if to is not None:
        kwargs["to"] = to
    if field is not None:
        kwargs["field"] = field
    if values is not None:
        kwargs["values"] = values
    return {
        "unique_id": test_id(name),
        "resource_type": "test",
        "name": name,
        "description": "",
        "columns": {},
        "tags": [],
        "depends_on": {"nodes": depends_on, "macros": []},
        "test_metadata": {"name": test_name, "kwargs": kwargs},
    }


TESTS: dict[str, dict[str, Any]] = {
    test_id("not_null_stg_players_player_id"): test_node(
        "not_null_stg_players_player_id",
        test_name="not_null",
        column_name="player_id",
        depends_on=[model_id("stg_players")],
    ),
    test_id("unique_stg_players_player_id"): test_node(
        "unique_stg_players_player_id",
        test_name="unique",
        column_name="player_id",
        depends_on=[model_id("stg_players")],
    ),
    test_id("accepted_values_stg_players_segment"): test_node(
        "accepted_values_stg_players_segment",
        test_name="accepted_values",
        column_name="segment",
        values=["casual", "core", "competitive"],
        depends_on=[model_id("stg_players")],
    ),
    test_id("not_null_stg_sessions_session_id"): test_node(
        "not_null_stg_sessions_session_id",
        test_name="not_null",
        column_name="session_id",
        depends_on=[model_id("stg_sessions")],
    ),
    test_id("unique_stg_sessions_session_id"): test_node(
        "unique_stg_sessions_session_id",
        test_name="unique",
        column_name="session_id",
        depends_on=[model_id("stg_sessions")],
    ),
    test_id("not_null_stg_sessions_player_id"): test_node(
        "not_null_stg_sessions_player_id",
        test_name="not_null",
        column_name="player_id",
        depends_on=[model_id("stg_sessions")],
    ),
    test_id("relationships_stg_sessions_player_id__player_id__ref_stg_players_"): test_node(
        "relationships_stg_sessions_player_id__player_id__ref_stg_players_",
        test_name="relationships",
        column_name="player_id",
        to="ref('stg_players')",
        field="player_id",
        depends_on=[model_id("stg_sessions"), model_id("stg_players")],
    ),
}


def build_manifest() -> dict[str, Any]:
    return {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/manifest/v12.json",
            "dbt_version": DBT_VERSION,
            "generated_at": GENERATED_AT,
            "project_name": PROJECT,
        },
        "nodes": {**MODELS, **TESTS},
        "sources": SOURCES,
    }


_WAREHOUSE_TYPES: dict[str, dict[str, str]] = {
    "players": {
        "player_id": "VARCHAR",
        "signup_at": "TIMESTAMP_NTZ",
        "segment": "VARCHAR",
        "region": "VARCHAR",
        "acquisition_channel": "VARCHAR",
    },
    "sessions": {
        "session_id": "VARCHAR",
        "player_id": "VARCHAR",
        "session_start": "TIMESTAMP_NTZ",
        "session_end": "TIMESTAMP_NTZ",
        "duration_minutes": "DOUBLE",
        "device": "VARCHAR",
    },
    "events": {"event_id": "VARCHAR", "session_id": "VARCHAR"},
    "fct_player_sessions": {
        "session_id": "VARCHAR",
        "player_id": "VARCHAR",
        "segment": "VARCHAR",
        "region": "VARCHAR",
        "session_start": "TIMESTAMP_NTZ",
        "signup_at": "TIMESTAMP_NTZ",
        "retained_7d": "BOOLEAN",
        "event_count": "BIGINT",
    },
    "mart_player_retention": {
        "segment": "VARCHAR",
        "region": "VARCHAR",
        "cohort_week": "DATE",
        "retention_7d": "DOUBLE",
        "player_count": "BIGINT",
    },
}

_CATALOG_ALIAS: dict[str, str] = {
    source_id("raw_players"): "players",
    source_id("raw_sessions"): "sessions",
    source_id("raw_events"): "events",
    model_id("stg_players"): "players",
    model_id("stg_sessions"): "sessions",
    model_id("fct_player_sessions"): "fct_player_sessions",
    model_id("mart_player_retention"): "mart_player_retention",
}


def _catalog_entry(unique_id: str) -> dict[str, Any]:
    alias = _CATALOG_ALIAS[unique_id]
    types = _WAREHOUSE_TYPES[alias]
    return {
        "metadata": {"type": "table", "schema": "analytics", "name": alias, "database": "analytics", "comment": None},
        "columns": {
            name: {"type": warehouse_type, "index": index, "name": name, "comment": None}
            for index, (name, warehouse_type) in enumerate(types.items(), start=1)
        },
        "stats": {},
    }


def build_catalog() -> dict[str, Any]:
    return {
        "metadata": {
            "dbt_schema_version": "https://schemas.getdbt.com/dbt/catalog/v1.json",
            "dbt_version": DBT_VERSION,
            "generated_at": GENERATED_AT,
        },
        "nodes": {unique_id: _catalog_entry(unique_id) for unique_id in MODELS},
        "sources": {unique_id: _catalog_entry(unique_id) for unique_id in SOURCES},
    }


def main() -> None:
    target = Path(__file__).parent / "target"
    target.mkdir(exist_ok=True)
    (target / "manifest.json").write_text(
        json.dumps(build_manifest(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (target / "catalog.json").write_text(json.dumps(build_catalog(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

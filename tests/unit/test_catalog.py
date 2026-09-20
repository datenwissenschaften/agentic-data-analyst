from pathlib import Path

from agentic_data_analyst.catalog.local import LocalParquetCatalog


def test_catalog_discovers_parquet_schema_and_annotations(sample_data_dir: Path) -> None:
    catalog = LocalParquetCatalog(sample_data_dir)

    players = catalog.get_dataset("players")

    assert players.name == "players"
    assert {column.name for column in players.columns} == {
        "player_id",
        "signup_at",
        "segment",
        "region",
        "acquisition_channel",
    }
    assert next(column for column in players.columns if column.name == "segment").description


def test_catalog_search_ranks_metadata_without_returning_full_schemas(
    catalog: LocalParquetCatalog,
) -> None:
    matches = catalog.search("retention and session duration", limit=3)

    assert matches[0].name == "sessions"
    assert all(not hasattr(candidate, "columns") for candidate in matches)
    assert len(matches) <= 3

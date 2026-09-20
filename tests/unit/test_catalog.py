import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.errors import CatalogError


def _write_dataset(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({"id": pa.array([1], type=pa.int64())}), path)


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
    assert next(column for column in players.columns if column.name == "signup_at").data_type == (
        "timestamp[us, tz=UTC]"
    )


def test_catalog_search_ranks_metadata_without_returning_full_schemas(
    catalog: LocalParquetCatalog,
) -> None:
    matches = catalog.search("retention and session duration", limit=3)

    assert matches[0].name == "sessions"
    assert all(not hasattr(candidate, "columns") for candidate in matches)
    assert len(matches) <= 3
    assert matches == catalog.search("retention and session duration", limit=3)


def test_catalog_discovers_nested_dataset(tmp_path: Path) -> None:
    path = tmp_path / "domain" / "players.parquet"
    _write_dataset(path)

    catalog = LocalParquetCatalog(tmp_path)

    assert catalog.get_dataset("players").path == str(path.resolve())


def test_catalog_rejects_duplicate_logical_names(tmp_path: Path) -> None:
    _write_dataset(tmp_path / "one" / "players.parquet")
    _write_dataset(tmp_path / "two" / "Players.parquet")

    with pytest.raises(CatalogError, match="Duplicate dataset name"):
        LocalParquetCatalog(tmp_path)


def test_catalog_rejects_parquet_symlink_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "catalog"
    root.mkdir()
    outside = tmp_path / "outside.parquet"
    _write_dataset(outside)
    (root / "linked.parquet").symlink_to(outside)

    with pytest.raises(CatalogError, match="outside catalog root"):
        LocalParquetCatalog(root)


def test_catalog_rejects_malformed_or_inconsistent_metadata(tmp_path: Path) -> None:
    malformed_root = tmp_path / "malformed"
    dataset = malformed_root / "players.parquet"
    _write_dataset(dataset)
    dataset.with_suffix(".metadata.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(CatalogError, match="Invalid metadata sidecar"):
        LocalParquetCatalog(malformed_root)

    relationship_root = tmp_path / "relationship"
    dataset = relationship_root / "sessions.parquet"
    _write_dataset(dataset)
    dataset.with_suffix(".metadata.json").write_text(
        json.dumps(
            {
                "description": "sessions",
                "relationships": [
                    {
                        "source_column": "id",
                        "target_dataset": "missing",
                        "target_column": "id",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="unknown dataset"):
        LocalParquetCatalog(relationship_root)


def test_catalog_reports_dataset_removed_after_discovery(tmp_path: Path) -> None:
    path = tmp_path / "players.parquet"
    _write_dataset(path)
    catalog = LocalParquetCatalog(tmp_path)
    path.unlink()

    with pytest.raises(CatalogError, match="no longer exists"):
        catalog.get_dataset("players")

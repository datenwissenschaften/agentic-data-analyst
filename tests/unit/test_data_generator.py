from pathlib import Path

import pyarrow.parquet as pq
import pytest

from agentic_data_analyst.catalog.local import LocalParquetCatalog
from agentic_data_analyst.data.generator import DATASET_NAMES, generate


def test_generator_is_deterministic_and_preserves_empty_table_schemas(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    generate(first, player_count=1, seed=7)
    generate(second, player_count=1, seed=7)

    for name in DATASET_NAMES:
        left = pq.read_table(first / f"{name}.parquet")
        right = pq.read_table(second / f"{name}.parquet")
        assert left.equals(right)
        assert left.schema.names
    assert {item.name for item in LocalParquetCatalog(first).list_datasets()} == set(DATASET_NAMES)


def test_generator_rejects_nonpositive_player_count(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        generate(tmp_path, player_count=0)

from pathlib import Path

import duckdb
import pytest

from agentic_data_analyst.database import connect
from agentic_data_analyst.seed import generate


@pytest.fixture(scope="session")
def database_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The real seed, generated once into a temporary file."""
    path = tmp_path_factory.mktemp("data") / "speedruns.duckdb"
    generate(path)
    return path


@pytest.fixture(scope="session")
def con(database_path: Path) -> duckdb.DuckDBPyConnection:
    """The read-only, sandboxed connection the app uses."""
    return connect(database_path)

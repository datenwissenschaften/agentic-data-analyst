from pathlib import Path

import duckdb
from pytest_bdd import parsers, scenarios, then, when

from agentic_data_analyst.seed import generate

scenarios("features/seed.feature")

TABLES = ("games", "categories", "levels", "runners", "runs", "splits")


def _rows(path: Path) -> dict[str, list[tuple[object, ...]]]:
    with duckdb.connect(str(path), read_only=True) as con:
        return {table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall() for table in TABLES}


@when("the seed is generated twice", target_fixture="generated")
def generate_twice(tmp_path: Path) -> tuple[Path, Path]:
    first, second = tmp_path / "first.duckdb", tmp_path / "second.duckdb"
    generate(first)
    generate(second)
    return first, second


@then("both databases contain the same rows")
def same_rows(generated: tuple[Path, Path]) -> None:
    assert _rows(generated[0]) == _rows(generated[1])


def _scalar(con: duckdb.DuckDBPyConnection, sql: str) -> object:
    row = con.cursor().execute(sql).fetchone()
    assert row is not None
    return row[0]


@then("every completed run has a time and frames")
def completed_runs_timed(con: duckdb.DuckDBPyConnection) -> None:
    assert _scalar(con, "SELECT COUNT(*) FROM runs WHERE status = 'completed'") != 0
    assert _scalar(con, "SELECT COUNT(*) FROM runs WHERE status = 'completed' AND (time_seconds IS NULL OR frames IS NULL)") == 0


@then("no reset or DNF run has a time")
def unfinished_runs_untimed(con: duckdb.DuckDBPyConnection) -> None:
    assert _scalar(con, "SELECT COUNT(*) FROM runs WHERE status IN ('reset', 'dnf')") != 0
    assert _scalar(con, "SELECT COUNT(*) FROM runs WHERE status <> 'completed' AND time_seconds IS NOT NULL") == 0


@then("human runners have a country and AI agents do not")
def countries(con: duckdb.DuckDBPyConnection) -> None:
    assert _scalar(con, "SELECT COUNT(*) FROM runners WHERE (kind = 'human') <> (country IS NOT NULL)") == 0


@then(parsers.parse('the AI methods are "{methods}"'))
def ai_methods(con: duckdb.DuckDBPyConnection, methods: str) -> None:
    found = con.cursor().execute("SELECT DISTINCT method FROM runners WHERE kind = 'ai' ORDER BY method").fetchall()
    assert [method for (method,) in found] == methods.split(", ")


@then("the last split of every completed run equals its time")
def splits_add_up(con: duckdb.DuckDBPyConnection) -> None:
    mismatches = _scalar(
        con,
        "SELECT COUNT(*) FROM runs r JOIN (SELECT run_id, MAX(cumulative_seconds) AS total FROM splits GROUP BY run_id) s "
        "USING (run_id) WHERE r.status = 'completed' AND abs(r.time_seconds - s.total) > 0.01",
    )
    assert mismatches == 0


@then(parsers.parse('in every category the best "{method}" time is lower than the best human time'))
def method_beats_humans(con: duckdb.DuckDBPyConnection, method: str) -> None:
    rows = (
        con.cursor()
        .execute(
            "SELECT category_id, MIN(time_seconds) FILTER (method = ?) AS ai, MIN(time_seconds) FILTER (kind = 'human') AS human "
            "FROM runs JOIN runners USING (runner_id) GROUP BY category_id",
            [method],
        )
        .fetchall()
    )
    assert rows
    for category_id, ai, human in rows:
        assert ai < human, f"category {category_id}: {ai} >= {human}"

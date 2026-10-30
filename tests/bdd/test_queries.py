import duckdb
import pytest
from pytest_bdd import parsers, scenarios, then, when

from agentic_data_analyst.database import MAX_ROWS, QueryError, QueryResult, run_query

scenarios("features/queries.feature")

Outcome = QueryResult | Exception


def _run(con: duckdb.DuckDBPyConnection, sql: str, timeout_seconds: float = 20.0) -> Outcome:
    try:
        return run_query(con, sql, timeout_seconds=timeout_seconds)
    except QueryError as error:
        return error


@when(parsers.parse('the analyst runs "{sql}"'), target_fixture="outcome")
def analyst_runs(con: duckdb.DuckDBPyConnection, sql: str) -> Outcome:
    return _run(con, sql)


@when(parsers.parse('the analyst runs "{sql}" with a timeout of {seconds:f} seconds'), target_fixture="outcome")
def analyst_runs_with_timeout(con: duckdb.DuckDBPyConnection, sql: str, seconds: float) -> Outcome:
    return _run(con, sql, timeout_seconds=seconds)


@when(parsers.parse('the database runs "{sql}" without the allowlist'), target_fixture="outcome")
def database_runs(con: duckdb.DuckDBPyConnection, sql: str) -> Outcome:
    """Bypasses check_sql, to prove the connection settings hold on their own."""
    cursor = con.cursor()
    try:
        cursor.execute(sql).fetchall()
    except duckdb.Error as error:
        return error
    finally:
        cursor.close()
    pytest.fail(f"The database ran {sql!r}")


def _result(outcome: Outcome) -> QueryResult:
    assert isinstance(outcome, QueryResult), outcome
    return outcome


@then(parsers.parse('the result has the columns "{columns}"'))
def has_columns(outcome: Outcome, columns: str) -> None:
    assert _result(outcome).columns == columns.split(", ")


@then(parsers.parse('the first row is "{values}"'))
def first_row(outcome: Outcome, values: str) -> None:
    assert [str(value) for value in _result(outcome).rows[0]] == values.split(", ")


@then(parsers.parse("the result has {rows:d} rows and is marked as truncated"))
def truncated(outcome: Outcome, rows: int) -> None:
    result = _result(outcome)
    assert rows == MAX_ROWS
    assert len(result.rows) == rows
    assert result.truncated


@then(parsers.parse('the query is rejected with "{reason}"'))
def rejected_with(outcome: Outcome, reason: str) -> None:
    assert isinstance(outcome, QueryError), outcome
    assert reason in str(outcome)


@then("the query is rejected")
def rejected(outcome: Outcome) -> None:
    assert isinstance(outcome, Exception), outcome

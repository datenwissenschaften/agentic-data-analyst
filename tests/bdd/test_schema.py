import json
from typing import Any

import duckdb
from pytest_bdd import parsers, scenarios, then, when

from agentic_data_analyst.database import QueryError, describe_table, list_tables

scenarios("features/schema.feature")


@when("the analyst lists the tables", target_fixture="tables")
def list_all(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return list_tables(con)


@then(parsers.parse('it sees the tables "{names}"'))
def sees_tables(tables: list[dict[str, Any]], names: str) -> None:
    assert [table["table"] for table in tables] == names.split(", ")


@then("every table has a description")
def tables_described(tables: list[dict[str, Any]]) -> None:
    assert all(table["description"] for table in tables)


@when(parsers.parse('the analyst describes the table "{name}"'), target_fixture="table")
def describe(con: duckdb.DuckDBPyConnection, name: str) -> dict[str, Any] | QueryError:
    try:
        return describe_table(con, name)
    except QueryError as error:
        return error


def _described(table: dict[str, Any] | QueryError) -> dict[str, Any]:
    assert isinstance(table, dict), table
    return table


@then("every column that is not a key has a description")
def columns_described(table: dict[str, Any] | QueryError) -> None:
    for column in _described(table)["columns"]:
        # Key columns explain themselves through the keys.
        if not column["name"].endswith("_id"):
            assert column["description"], column["name"]


@then(parsers.parse('it sees the key "{key}"'))
def sees_key(table: dict[str, Any] | QueryError, key: str) -> None:
    assert key in _described(table)["keys"]


@then("it sees no rows of data")
def no_rows(table: dict[str, Any] | QueryError, con: duckdb.DuckDBPyConnection) -> None:
    played_at = con.cursor().execute("SELECT CAST(played_at AS VARCHAR) FROM runs LIMIT 1").fetchone()
    assert played_at is not None
    assert played_at[0] not in json.dumps(_described(table))


@then("it is told the table is unknown")
def unknown_table(table: dict[str, Any] | QueryError) -> None:
    assert isinstance(table, QueryError)
    assert "Unknown table" in str(table)

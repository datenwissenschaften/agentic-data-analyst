"""The analyst's only access to data: schema inspection and guarded execution of model-generated SQL.

Deterministic layers enforce the security boundary, not the prompt and not the reviewer agent:
1. Before execution, the SQL must parse to exactly one SELECT that reads only the data tables (an allowlist checked
   on DuckDB's own syntax tree), and no table functions except a few generators.
2. The database file is opened read-only, without access to other files, the network or extensions, with bounded
   memory and threads, and with settings locked so a query cannot loosen them.
3. Each query gets a deadline and returns a bounded number of rows.
"""

import json
import threading
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from math import isfinite
from pathlib import Path

import duckdb

MAX_ROWS = 200
TIMEOUT_SECONDS = 20.0
# A useful analytical query fits in a few thousand characters; the bound limits cost and abuse.
MAX_SQL_CHARS = 8000
# The data tables; system tables (duckdb_settings(), information_schema) are not needed and stay out of reach.
DATA_TABLES = frozenset({"games", "categories", "levels", "runners", "runs", "splits"})
# Table functions that only generate values, e.g. a calendar of quarters. File readers such as read_csv are excluded.
TABLE_FUNCTIONS = frozenset({"range", "generate_series", "unnest"})
# The seed is a few MB; the limits keep one heavy query from starving the app or other chats.
RESOURCE_LIMITS: dict[str, str | int] = {"memory_limit": "1GB", "threads": 2}

type Value = str | int | float | bool | None


class QueryError(Exception):
    """The SQL was rejected or failed; the message is safe to show to the model and the user."""


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Value]]
    # True when the query returned more than MAX_ROWS rows and the rest was dropped.
    truncated: bool


def connect(path: Path) -> duckdb.DuckDBPyConnection:
    if not path.is_file():
        raise FileNotFoundError(f"{path} does not exist. Create it with `make data`.")
    return duckdb.connect(
        str(path),
        read_only=True,
        config={
            "enable_external_access": False,
            "autoload_known_extensions": False,
            "autoinstall_known_extensions": False,
            **RESOURCE_LIMITS,
            "lock_configuration": True,
        },
    )


def list_tables(con: duckdb.DuckDBPyConnection) -> list[dict[str, object]]:
    """The data tables with their descriptions and approximate size - metadata only, never rows."""
    cursor = con.cursor()
    rows = cursor.execute(
        "SELECT table_name, comment, estimated_size FROM duckdb_tables() WHERE NOT internal ORDER BY table_name"
    ).fetchall()
    return [{"table": table, "description": comment, "approximate_rows": size} for table, comment, size in rows if table in DATA_TABLES]


def describe_table(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, object]:
    """Columns (type, nullability, description) and keys of one data table - metadata only, never rows."""
    if table not in DATA_TABLES:
        raise QueryError(f"Unknown table {table!r}; use one of {', '.join(sorted(DATA_TABLES))}.")
    cursor = con.cursor()
    description = cursor.execute("SELECT comment FROM duckdb_tables() WHERE table_name = ?", [table]).fetchone()
    columns = cursor.execute(
        "SELECT column_name, data_type, is_nullable, comment FROM duckdb_columns() WHERE table_name = ? ORDER BY column_index", [table]
    ).fetchall()
    constraints = cursor.execute(
        "SELECT constraint_type, constraint_column_names, referenced_table, referenced_column_names FROM duckdb_constraints() "
        "WHERE table_name = ? AND constraint_type IN ('PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE') ORDER BY constraint_index",
        [table],
    ).fetchall()
    return {
        "table": table,
        "description": description[0] if description else None,
        "columns": [
            {"name": name, "type": data_type, "nullable": nullable, "description": text} for name, data_type, nullable, text in columns
        ],
        "keys": [_key(*constraint) for constraint in constraints],
    }


def _key(kind: str, columns: list[str], referenced_table: str | None, referenced_columns: list[str]) -> str:
    key = f"{kind} ({', '.join(columns)})"
    return key if referenced_table is None else f"{key} REFERENCES {referenced_table} ({', '.join(referenced_columns)})"


def run_query(
    con: duckdb.DuckDBPyConnection, sql: str, *, max_rows: int = MAX_ROWS, timeout_seconds: float = TIMEOUT_SECONDS
) -> QueryResult:
    check_sql(sql)
    # A cursor is a separate connection to the same database, so concurrent chats do not block each other.
    cursor = con.cursor()
    timer = threading.Timer(timeout_seconds, cursor.interrupt)
    timer.start()
    try:
        cursor.execute(sql)
        columns = [description[0] for description in cursor.description or []]
        rows = cursor.fetchmany(max_rows + 1)
    except duckdb.InterruptException as error:
        raise QueryError(f"The query took longer than {timeout_seconds:g} seconds and was stopped.") from error
    except duckdb.Error as error:
        raise QueryError(str(error)) from error
    finally:
        timer.cancel()
        cursor.close()
    return QueryResult(columns, [[_value(value) for value in row] for row in rows[:max_rows]], truncated=len(rows) > max_rows)


def check_sql(sql: str) -> None:
    """Reject anything but one SELECT over the data tables before it reaches the database."""
    if len(sql) > MAX_SQL_CHARS:
        raise QueryError(f"The query is longer than {MAX_SQL_CHARS:,} characters.")
    try:
        statements = duckdb.extract_statements(sql)
    except duckdb.Error as error:
        raise QueryError(str(error)) from error
    if len(statements) != 1:
        raise QueryError(f"Send exactly one SQL statement, not {len(statements)}.")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise QueryError(f"Only SELECT queries are allowed, not {statements[0].type.name}.")
    tables, functions, ctes = _references(sql)
    unknown = sorted(tables - DATA_TABLES - ctes)
    if unknown:
        raise QueryError(f"Only the tables {', '.join(sorted(DATA_TABLES))} can be queried, not {', '.join(unknown)}.")
    forbidden = sorted(functions - TABLE_FUNCTIONS)
    if forbidden:
        raise QueryError(f"Table functions other than {', '.join(sorted(TABLE_FUNCTIONS))} are not allowed: {', '.join(forbidden)}.")


def _references(sql: str) -> tuple[set[str], set[str], set[str]]:
    """Tables, table functions and CTE names of a query, from DuckDB's syntax tree rather than from regexes."""
    # A separate in-memory database: parsing must not depend on, or touch, the data.
    with duckdb.connect(":memory:") as parser:
        row = parser.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()
    tree = json.loads(row[0]) if row else {"error": True}
    if tree.get("error"):
        raise QueryError(f"The query could not be parsed: {tree.get('error_message', 'unknown error')}")
    tables: set[str] = set()
    functions: set[str] = set()
    ctes: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "BASE_TABLE":
            schema = node.get("schema_name") or "main"
            tables.add(node["table_name"].lower() if schema == "main" else f"{schema}.{node['table_name']}".lower())
        if node.get("type") == "TABLE_FUNCTION":
            functions.add(str(node.get("function", {}).get("function_name", "")).lower())
        for entry in node.get("cte_map", {}).get("map", []):
            ctes.add(str(entry["key"]).lower())
        for value in node.values():
            walk(value)

    walk(tree["statements"])
    return tables, functions, ctes


def _value(value: object) -> Value:
    """JSON-ready values: dates as ISO strings, decimals as floats, non-finite floats as text."""
    if isinstance(value, float) and not isfinite(value):
        return str(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)

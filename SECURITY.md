# Security policy

## Threat model

User questions, model output (generated SQL, chart choices, replies) and query results are untrusted. The seed
database, application code, configuration and the DuckDB library are trusted operator inputs.

The security boundary is deterministic and lives in `src/agentic_data_analyst/database.py`. It holds whatever the
analyst or the reviewer model decides:

- Generated SQL must parse to exactly one `SELECT`. Its syntax tree may reference only the six data tables (and its
  own CTEs) and no table functions except `range`, `generate_series` and `unnest`.
- The database file is opened read-only, with external access disabled (no other files, no network), extension
  autoloading and installing disabled, memory and threads bounded, and the configuration locked so a query cannot
  loosen any of this.
- Every query has a deadline (interrupted after 20 s) and returns at most 200 rows.
- The analyst loop is bounded in rounds and in cost per answer and per chat.

The SQL reviewer agent is defence in depth for correctness, not part of the security boundary.

## Known limitations

- There is no authentication, authorization or rate limiting. The per-chat cost budget resets with a new chat.
- Prompt injection can change *which* SELECT the analyst writes. It cannot make the app write data, read files,
  reach the network or exceed the deadline, row cap or budgets.
- Questions, schema metadata and query results are sent to the Anthropic API.

## Reporting a vulnerability

Please use GitHub's private security-advisory reporting for this repository. Include the affected version,
reproduction steps, impact and any suggested mitigation. Avoid filing public issues for vulnerabilities until a
fix is available.

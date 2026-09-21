# Security policy

## Generated-analysis threat model

Natural-language questions, LLM responses, and descriptive catalog metadata are untrusted.
This includes metadata read from dbt artifacts (`manifest.json`/`catalog.json`) when
`DBT_PROJECT_PATH` is configured: model/source descriptions, column descriptions, tags, and
declared test targets are attacker-influenceable free text in the same way a hand-written
catalog sidecar description is, and flow through the identical `StrictModel` contracts and
"untrusted data" prompt framing. A dbt model with no matching physical Parquet dataset can
never be selected or executed; see `agentic_data_analyst/dbt/catalog.py` for the mechanism.
The application never evaluates model-produced Python or SQL. Structured provider responses
must validate as strict Pydantic models; unknown fields and unsupported discriminated-union
operations fail closed.

Only a semantically valid `spark_dataframe_ir/v1` can reach the compiler. The validator
authorizes catalog datasets, canonicalizes existing paths below the configured catalog root,
checks selected columns, relation lineage, and compatible expression operand types, rejects
unsupported nodes, bounds expression and plan complexity, and requires a final result limit.
It returns an internal capability with a snapshot of the approved paths and columns. Both
preview rendering and execution compilation accept that capability and use an exhaustive
mapping to PySpark DataFrame operations.

The IR has no operations for Python imports or evaluation, environment variables, networks,
processes, shell commands, arbitrary URLs or paths, Spark SQL strings, JVM access, UDFs,
Spark configuration, or writes. These properties constrain model-generated analysis; they
do not make the Python process or Spark runtime a general sandbox.

## Trusted components and limitations

Application code, runtime configuration, the catalog root and its contents, Python, Java,
and Spark are trusted operator inputs. A privileged actor who can replace files after path
authorization can violate assumptions outside this model. The OpenRouter provider receives
the question and the metadata selected for each model stage.

Spark runs in the API process with one shared session. It provides no hostile multi-tenant
isolation, per-request memory or CPU quota, or guaranteed termination. The configurable
deadline calls Spark job-group cancellation, which is cooperative and may not interrupt
blocked JVM or native work. Deploy untrusted tenants through isolated worker processes or
containers with external time and resource enforcement. The reference API also has no
authentication, authorization, rate limiting, or persistent audit log.

## Reporting a vulnerability

Please use GitHub's private security-advisory reporting feature for this repository. Include
the affected version, reproduction steps, impact, and any suggested mitigation. Avoid filing
public issues for vulnerabilities until a fix is available.

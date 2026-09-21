# `gaming_analytics` — synthetic example dbt project

This is a **synthetic, hand-authored example** dbt project documenting the same
gaming/product analytics domain as `data/sample`. It exists to give
`agentic_data_analyst.dbt` real dbt artifacts to parse and to demonstrate the
integration without requiring a running data warehouse or dbt-core itself. It
is not a real company's schema and contains no proprietary data or naming.

```
raw_players ────────▶ stg_players ─────────┐
                                            ▼
raw_sessions ───────▶ stg_sessions ──▶ fct_player_sessions ──▶ mart_player_retention
                                            ▲
raw_events ─────────────────────────────────┘
```

- **Sources** (`models/staging/_staging.yml`): `raw_players`, `raw_sessions`,
  `raw_events` — the raw landing tables. Their `identifier` points at the
  same physical Parquet files as `data/sample` (`players`, `sessions`,
  `events`), so this example's dbt sources describe real, queryable data.
- **Staging models**: `stg_players`, `stg_sessions` — curated, one-row-per-entity
  models. Their `alias` also resolves to the physical `players`/`sessions`
  datasets, so `agentic_data_analyst.dbt.DbtEnrichedCatalog` attaches their
  richer descriptions, tests, and lineage to those datasets (staging metadata
  wins over the raw source when both match, since it is the more curated
  layer — see `dbt/catalog.py`).
- **Marts**: `fct_player_sessions`, `mart_player_retention` — a session-level
  fact table and a retention-rate rollup. **Neither is materialized as a
  physical dataset in this reference deployment.** They exist only as
  lineage/description context: their text can raise the search ranking of the
  physical datasets upstream of them (e.g. a question about "7-day retention"
  ranks `sessions`/`players` higher because `mart_player_retention`'s
  description mentions `retention_7d`), but they can never be selected,
  planned against, or executed — `Catalog.get_dataset()` only ever returns
  datasets with an authorized physical path. This is deliberate: adding a dbt
  transformation/execution engine is out of scope, and it is also the
  concrete mechanism that keeps dbt lineage from ever becoming an execution
  authorization.
- **Tests**: `models/staging/_staging.yml` declares `not_null`, `unique`,
  `accepted_values`, and `relationships` tests. These are surfaced as
  `QualityExpectationMetadata` — declared expectations, not evidence that the
  current Parquet snapshot satisfies them. Nothing in this project ever runs
  a dbt test.

## What is actually consumed

`agentic_data_analyst.dbt.DbtArtifactLoader` reads **`target/manifest.json`**
(required) and **`target/catalog.json`** (optional) — the artifacts dbt itself
writes after `dbt parse` / `dbt docs generate`. It never reads the `.sql` or
`.yml` files directly and never invokes dbt-core.

The committed `target/manifest.json` and `target/catalog.json` were generated
by `generate_artifacts.py` in this directory rather than by a real dbt run, so
this example works without installing dbt or a warehouse. They are shaped to
match the fields documented dbt manifest schema **v12** and catalog schema
**v1** use (also accepts manifest **v11**), but they are not a dbt-validated
dump — do not treat them as a reference for the full artifact schema.

To regenerate them:

```bash
poetry run python examples/dbt/gaming_analytics/generate_artifacts.py
```

To point `agentic-data-analyst` at a *real* dbt project's artifacts instead,
run `dbt parse` (and `dbt docs generate` for column types) in that project and
set `DBT_PROJECT_PATH` to its `target/` directory.

# MongoDB ingestion

**Namespace:** `census.Ingestion` ·
**FFL:** `src/census_us/handlers/ingestion/ffl/census_ingestion.ffl` ·
**Handlers:** `src/census_us/handlers/ingestion/ingestion_handlers.py` ·
**Impl:** `src/census_us/tools/_lib/db_ingest.py` ·
**CLI:** `src/census_us/tools/ingest-to-db.sh` ·
**Tests:** `tests/test_ingestion_handlers.py`

## Overview

The persistence tier: take an upstream handler's output file (ACS CSV, TIGER/joined
GeoJSON, or summary JSON) and **upsert** it into MongoDB so the data is queryable
later rather than only living in the run's step payload. 15 `*ToDB` facets, one per
dataset kind. Used only by the `AnalyzeStateWithDB` workflow — the map pipelines skip
it (their output is the HTML map, not a queryable table).

## How it works

Every handler builds an `OutputStore(get_mongo_db())` and calls the matching
`ingest_*` method:

- **ACS CSVs** (`_make_acs_db_handler(table_id)`, 12 facets) → `store.ingest_csv`
  keyed on `GEOID`, dataset key `census.acs.<table>.<state>`.
- **TIGER county GeoJSON** (`CountiesToDB`) → `store.ingest_geojson`, key
  `census.tiger.county.<state>`.
- **Joined GeoJSON** (`JoinedToDB`) → `ingest_geojson`, key `census.joined.<state>`.
- **Summary JSON** (`SummaryToDB`) → `ingest_json`, key `census.summary.<state>`.

`OutputStore` bulk-upserts into two collections — `handler_output` (the rows/features)
and `handler_output_meta` (per-dataset metadata) — under a **compound unique index on
`(dataset_key, feature_key)`**, so re-runs replace data without duplicating it, plus a
`2dsphere` index on geometry. Each handler returns an `IngestionResult`
(`dataset_key, record_count, data_type, imported_at`).

## Fan-out

**Single-task per facet.** In `AnalyzeStateWithDB` the 15 ingests run as parallel
steps off the already-extracted files; the whole workflow fans out per state at the
`AnalyzeStates_03`-style level, not inside ingestion.

## Data & fields

- **Target DB:** `FW_EXAMPLES_DATABASE` (default `facetwork_examples`) on
  `FW_MONGODB_URL` (default `mongodb://afl-mongodb:27017`) — deliberately isolated
  from the FFL runtime database.
- **Feature key:** `GEOID` for CSV/GeoJSON; `state_fips` for the summary JSON.
- **Dataset keys** namespace each dataset (`census.acs.b19013.06`, `census.joined.06`,
  …) so a re-run of one state/table replaces exactly that slice.
- **Schema:** `IngestionResult` (`dataset_key, record_count, data_type, imported_at`).

## External libraries / binaries

- **`pymongo`** (pip, the `[mongodb]` extra) — imported at module top in
  `db_ingest.py` (`MongoClient`, `ReplaceOne`). `db_ingest` is the one `_lib` module
  that depends on Mongo; because the handler-side shim imports it, the ingestion
  handlers require the `[mongodb]` extra installed. A running **MongoDB** instance is
  required at execution time.

## Facets & workflows

15 event facets, all `with Effect(kind = "external")` / `with Cost(tier = "cheap")`,
all `XToDB(result: <ACSResult|TIGERResult|CensusSummary>, state_fips: String) =>
(ingestion: IngestionResult)`:

`PopulationToDB, IncomeToDB, HousingToDB, EducationToDB, CommutingToDB, TenureToDB,
HouseholdsToDB, AgeToDB, VehiclesToDB, RaceToDB, PovertyToDB, EmploymentToDB`
(ACS CSVs) · `CountiesToDB` (TIGER) · `JoinedToDB` (joined GeoJSON) · `SummaryToDB`
(summary JSON). Driven exclusively by `census.workflows.AnalyzeStateWithDB`.

## Cache / output

Writes to MongoDB (`handler_output` / `handler_output_meta`), not the file cache — the
one tier whose output isn't a file. Reads the file paths produced by the extract /
join / summary tiers.

## Gotchas & notes

- **Requires the `[mongodb]` extra + a live MongoDB.** Without pymongo the ingestion
  handlers can't even import; without a reachable Mongo the upsert fails. The CLIs and
  map pipelines don't need it — only `AnalyzeStateWithDB`.
- **Idempotent by design.** The `(dataset_key, feature_key)` unique index means
  re-running a state overwrites rather than duplicates — safe to retry.
- **Isolated database.** Ingested data lands in `facetwork_examples`, not the runtime
  DB, so it can't collide with workflow state.

## Related specs

- [acs-extraction](acs-extraction.md) / [tiger-geometry](tiger-geometry.md) / [summary-and-join](summary-and-join.md) — produce the files this persists.
- [workflows](workflows.md) — `AnalyzeStateWithDB` is the only caller.
- [storage-and-cache](storage-and-cache.md) — the file backend the ingested paths point at.

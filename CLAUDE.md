# CLAUDE.md — census-us

This repository is a **standalone Facetwork example package**. The Facetwork
platform (workflow compiler + runtime) lives at
`/Users/ralph_lemke/facetwork`; this repo only contains US-Census-specific
FFL, handlers, and tools. The two are wired together via the
`facetwork.examples` entry point in `pyproject.toml`.

## Quick orientation

```
fwh_census_us/
├── pyproject.toml                  # declares the facetwork.examples entry point
├── src/census_us/__init__.py       # exports `example: ExamplePackage`
├── src/census_us/handlers/         # event-facet implementations (5 subpackages)
├── src/census_us/ffl/              # top-level FFL workflows
├── src/census_us/handlers/<domain>/ffl/   # per-domain FFL files
├── src/census_us/tools/            # CLI utilities + _lib/ (the real implementation)
├── tests/                          # repo-level integration tests
└── agent-spec/                     # cross-cutting design specs
```

## Common operations

```bash
# Register this package with Facetwork's runner
pip install -e ".[mongodb]"

# From a Facetwork checkout:
scripts/seed-examples --include census-us
scripts/start-runner --example census-us -- --log-format text

# CLIs (call the same _lib/ as the handlers — see Tools pattern below):
src/census_us/tools/download.sh --kind acs --variable B01003 --states CA,TX
src/census_us/tools/acs-extract.sh --variable B19013 --state CA
src/census_us/tools/tiger-extract.sh --state CA --layer county
src/census_us/tools/ingest-to-db.sh --variable B01003 --state CA
src/census_us/tools/summarize-state.sh --state CA

# Tests
pytest tests/ src/census_us/handlers/ -v
```

## Key concepts

### Tools / handlers / cache pattern

Every operation has two surfaces — a CLI under `src/census_us/tools/`
and an FFL handler under `src/census_us/handlers/<domain>/` — and both
call into the **same** implementation in `src/census_us/tools/_lib/`.
This is the Facetwork canonical pattern (see
`agent-spec/tools-pattern.agent-spec.yaml`).

```
                       ┌────────────────────────────┐
   CLI tool ───────────┤                            │
                       │   tools/_lib/X.py          │ ← single source of truth
   FFL handler ────────┤   (downloader / extractor /│
   (via shared shim)   │    db_ingest / summary)    │
                       └────────────────────────────┘
```

The shim lives at `src/census_us/handlers/shared/census_utils.py`. It
re-exports `_lib` symbols via the **fully-qualified** package path
(`from census_us.tools._lib.downloader import …`) — never the bare
`_lib` name — so this package coexists cleanly with sibling Facetwork
packages (osm-geocoder, noaa-weather, jenkins) that also ship
`tools/_lib/`.

The MongoDB-touching code stays handler-side via the shim; `_lib`
modules **must not** import `pymongo` so the CLIs are runnable without
a Mongo cluster. (`db_ingest.py` is the one exception — it lives in
`_lib` because all its callers already require Mongo, but it imports
pymongo lazily inside functions.)

### Handler / domain map

| Subpackage | Domain | Facets |
|------------|--------|--------|
| `downloads/` | `census.Operations` | `DownloadACS`, `DownloadTIGER`, `DownloadACSDetailed` |
| `acs/` | `census.ACS` | One per ACS variable (population, income, education, housing, …) |
| `tiger/` | `census.TIGER` | County geometry extraction per state |
| `ingestion/` | `census.Ingestion` | 15 `*ToDB` upsert handlers |
| `summary/` | `census.Summary` | `JoinGeo`, `SummarizeState` |

Each module exposes `register_handlers(runner)` for the RegistryRunner;
all five are wired into `register_all_registry_handlers` in
`src/census_us/handlers/__init__.py`.

### Gotchas (learned the hard way)

- **GEOID join formats differ.** TIGER county features carry the bare FIPS in
  `GEOID` (`"56023"`; the prefixed form is in `GEOIDFQ`), but ACS rows carry the
  prefixed `GEOID` (`"0500000US56023"`). `JoinGeo` normalizes both to bare FIPS
  via `_norm_geoid()` (`summary_builder.py`) — DO NOT join the two raw `GEOID`
  fields directly or every ACS column silently fails to merge (geometry-only
  output).
- **The default ACS pull is a fixed column list** (`download_acs`). If an
  `Extract*` handler comes back empty, its table's columns probably aren't in
  that list (poverty/B17001 + employment/B23025 were missing until added;
  race/B02001 is still absent). Stay under the API's 50-variable/request cap.
- **`CENSUS_API_KEY` is required** — ACS5 returns an empty body without it
  (→ a JSON parse error). The downloader appends it to the *request* URL only,
  never the cached/returned `url` (keep the secret out of step payloads/Mongo).
- **Storage is `AFL_STORAGE`-aware** (`_lib/storage.py`): `cache_root()` /
  `output_root()` resolve under `AFL_DATA_ROOT` (s3:// on the fleet); writers
  stage-then-finalize, readers `localize()` remote URIs before
  `open`/`csv`/`zipfile`/`fiona`. Build paths with `cstore.join` (never
  `os.path.join` — it mangles `s3://`) and check existence with `cstore.exists`.
- **`AnalyzeState` does NOT join age (B01001)** into its GeoJSON;
  `BuildVulnerabilityMap` includes it (the SVI's 65+ indicator needs it).

### Cache layout

Both the CLIs and the FFL handlers read/write the same on-disk cache:

```
$AFL_DATA_ROOT/cache/census-us/                   (or $AFL_CENSUS_CACHE_DIR)
├── acs/                            # raw ACS API responses (JSON)
├── tiger/                          # downloaded shapefiles + GeoJSON conversions
├── extracts/                       # per-variable per-state extractions
└── summaries/                      # state-level rollups for the dashboard map
```

## Adding new handlers

1. Add the real implementation to `src/census_us/tools/_lib/<name>.py`
   (no MongoDB or facetwork.runtime imports — those stay in the shim
   or handler).
2. Re-export the new symbols from
   `src/census_us/handlers/shared/census_utils.py`.
3. Add a CLI wrapper at `src/census_us/tools/<verb>-<noun>.py` plus a
   thin `<verb>-<noun>.sh` wrapper.
4. Add a Python module under `src/census_us/handlers/<domain>/` that
   exports `register_handlers(runner)` and adds the facet to its
   `_DISPATCH`. Wire it into `register_all_registry_handlers`.
5. Drop the FFL declaration into the right
   `src/census_us/handlers/<domain>/ffl/` (or top-level `ffl/`).
6. Re-run `scripts/seed-examples --include census-us` so the new flow
   shows up in the dashboard.

## Code review checklist

- For every state transition: "what if this crashes halfway?" Design the recovery path.
- For every download: cache + per-path lock + max-age check.
- For every retry: max count and backoff. No infinite loops.
- For every error handler: never silently return empty defaults. Fail explicitly or re-raise.
- Keep `_lib/` free of `facetwork.runtime` and lazy on `pymongo` so CLIs stay runnable standalone.

## Domain research before implementation

For US Census / ACS work:
- ACS table IDs are 6 chars with a letter prefix (`B01003`, `B19013`); the API endpoint is `https://api.census.gov/data/<year>/acs/acs5`.
- An API key is required for >50 calls/day — set `CENSUS_API_KEY`.
- TIGER/Line shapefiles are versioned by year and partitioned by state FIPS code (`https://www2.census.gov/geo/tiger/TIGER<year>/COUNTY/`).
- Geographic resolution: state, county, tract, block group, block — pick the smallest that the variable's universe supports.
- ACS estimates carry margin-of-error columns (`B01003_001M`); preserve them when ingesting.

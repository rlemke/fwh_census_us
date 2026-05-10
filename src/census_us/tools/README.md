# census-us tools

CLI utilities for the four core operations of the census-us pipeline.
Each operation has:

- a Python module under `_lib/<name>.py` with the real implementation,
- a CLI script `<verb>_<noun>.py` that argparse-parses input and prints
  JSON,
- a thin shell wrapper `<verb>-<noun>.sh`.

The FFL handlers in `src/census_us/handlers/` call into the same
`_lib/` modules via `handlers/shared/census_utils.py`, so both surfaces
share one implementation and one cache.

## CLI map

| Domain | CLI | What it does |
|--------|-----|--------------|
| Download | `download.sh --kind acs --state-fips 06` | Pull ACS demographics CSV for one state |
| Download | `download.sh --kind tiger --state-fips 06` | Pull TIGER/Line shapefile ZIP for one state |
| ACS | `acs-extract.sh --csv … --table B01003 --state-fips 06` | Pull a specific ACS table out of a downloaded CSV |
| TIGER | `tiger-extract.sh --zip … --state-fips 06` | Parse county geometry out of a TIGER ZIP |
| Summary | `join-geo.sh --acs-path … --tiger-path … [--extra-acs …]` | Merge ACS rows into county GeoJSON for choropleth mapping |

The two **MongoDB ingestion** operations (`*ToDB` family in
`handlers/ingestion/`) and **per-state summary** rollup
(`SummarizeState` in `handlers/summary/`) don't ship CLI wrappers
because their input shapes are workflow-internal — pass-through dicts
of all 12 ACS variables. Use the FFL workflows for those steps:

```bash
scripts/seed-examples --include census-us
# Submit `census.workflows.AnalyzeStateWithDB` with `state_fips` from the dashboard
```

If you need an ad-hoc ingestion or summary outside FFL, call the
corresponding `_lib/` function directly — `db_ingest.OutputStore`,
`summary_builder.summarize_state`.

## Conventions

- Help: `<cli>.sh --help` — every CLI uses argparse.
- Stderr: one-line human summary mirroring the FFL step log.
- Stdout: pretty-printed JSON dict (the same shape the FFL handler emits).
- Exit code: 0 on success, non-zero on argparse error.
- Imports: every CLI uses `from census_us.tools._lib.<name> import …`
  so this package coexists cleanly with sibling Facetwork example
  packages on `sys.modules`.

## Example: minimal pipeline from the shell

```bash
# 1. Download California (FIPS 06) ACS + TIGER
ACS=$(src/census_us/tools/download.sh --kind acs --state-fips 06 | jq -r '.local_path')
TIGER=$(src/census_us/tools/download.sh --kind tiger --state-fips 06 | jq -r '.local_path')

# 2. Pull income (B19013) for every CA county
src/census_us/tools/acs-extract.sh \
  --csv "$ACS" --table B19013 --state-fips 06 > /tmp/ca-income.json

# 3. Pull CA county polygons
src/census_us/tools/tiger-extract.sh \
  --zip "$TIGER" --state-fips 06 > /tmp/ca-counties.json

# 4. Join them into a choropleth-ready GeoJSON
src/census_us/tools/join-geo.sh \
  --acs-path /tmp/ca-income.json \
  --tiger-path /tmp/ca-counties.json > /tmp/ca-income-choropleth.json
```

## Adding a new tool

1. Add the real implementation to `_lib/<name>.py` (or extend an
   existing module). Keep `_lib/` free of `facetwork.runtime` and lazy
   on `pymongo`.
2. Re-export from `src/census_us/handlers/shared/census_utils.py`.
3. Copy an existing CLI here as a template; adjust argparse and the
   function call.
4. `chmod +x` the new `.py` and create the matching `.sh` wrapper:
   `printf '#!/usr/bin/env bash\nexec python3 "$(dirname "$0")/<n>.py" "$@"\n' > <n>.sh && chmod +x <n>.sh`
5. If the CLI corresponds to an FFL facet, wire it through the
   matching handler module's `_DISPATCH`.

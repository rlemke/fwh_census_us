# census-us

A standalone [Facetwork](https://github.com/rlemke/facetwork) example package
providing FFL workflows and handlers for working with US Census Bureau data:

- **ACS demographics** — pull American Community Survey variables (population, income, education, housing, commuting, tenure, age, vehicles, race, poverty, employment, …) via the Census REST API
- **TIGER shapefiles** — fetch county / tract geometry from the TIGER/Line endpoint
- **MongoDB ingestion** — upsert per-state ACS variables and county geometry into `census_*` collections
- **Per-state summaries** — compute state-level rollups + join census variables to TIGER county geometry for choropleth visualization
- **Dashboard map** — county-level choropleth in Facetwork's dashboard with switchable variables (density, income, education, commuting, …)
- **Social Vulnerability Index (SVI)** — compute a 6-indicator CDC/ATSDR-style vulnerability index per county and render a MapLibre choropleth; fan out across all 50 states + DC and link them from a national index page (see [below](#social-vulnerability-index-svi))

Outputs (cache + GeoJSON + maps) follow `AFL_STORAGE`: on the fleet they land in
shared MinIO (`s3://afl-cache/cache/census-us/`); locally under
`$AFL_DATA_ROOT`.

Discovered by the Facetwork runner via the `facetwork.examples` entry point
declared in `pyproject.toml`. After `pip install -e .`, Facetwork's
`scripts/start-runner --example census-us` and `scripts/seed-examples`
pick this package up automatically.

## Install

```bash
git clone https://github.com/rlemke/fwh_census_us.git ~/fw_handlers/fwh_census_us
cd ~/fw_handlers/fwh_census_us
pip install -e ".[mongodb]"     # MongoDB extras enable the ingestion handlers
```

This registers the package under the `facetwork.examples` entry-point group,
making it discoverable by any Facetwork installation in the same environment.

## Run from a Facetwork checkout

```bash
scripts/seed-examples --include census-us           # one-time, seeds FFL
scripts/start-runner --example census-us -- --log-format text
```

This brings up the dashboard on `:8080` and a runner that polls for
census-us tasks.

## Run a single census operation from the command line

Every domain operation also has a CLI under `src/census_us/tools/`,
backed by the same `tools/_lib/` modules the FFL handlers call. So you
can pull data, build summaries, or load Mongo from the shell without
threading a workflow:

```bash
src/census_us/tools/download.sh --kind acs --variable B01003 --states CA,TX,NY
src/census_us/tools/acs-extract.sh --variable B19013 --state CA
src/census_us/tools/tiger-extract.sh --state CA --layer county
src/census_us/tools/ingest-to-db.sh --variable B01003 --state CA
src/census_us/tools/summarize-state.sh --state CA
src/census_us/tools/join-geo.sh --state CA --variable B19013
```

The CLIs print a JSON dict on stdout (the same shape the FFL handler
emits) and a human-readable summary on stderr. They never touch
Facetwork's runtime, so they're runnable standalone.

## Social Vulnerability Index (SVI)

A county-level vulnerability choropleth, built on the existing download → extract
→ join chain (`namespace census.Vulnerability`, `tools/_lib/svi.py`).

**Methodology** — six indicators, each "higher = more vulnerable", percentile-
ranked across the counties in the input and averaged into an SVI in `[0,1]`
(1 = most vulnerable): below-poverty (B17001), unemployment (B23025),
no-bachelor's (B15003), aged-65+ (B01001), no-vehicle (B25044), and
renter-occupied (B25003). Because counties are ranked **within the input set**,
SVI percentiles are comparable *within* a state but not *across* states; raw
rates (e.g. poverty %) are nationally comparable.

| FFL | What it does |
|-----|--------------|
| `census.Vulnerability.BuildSVIMap(joined_path, region, title)` | Compute the SVI from a `JoinGeo` output GeoJSON + render a MapLibre choropleth (per-component click popups) → `output/svi/<region>/index.html` |
| `census.workflows.BuildVulnerabilityMap(state_fips, state_name)` | One state, end-to-end: download → extract (incl. age) → join → `BuildSVIMap` |
| `census.workflows.BuildVulnerabilityMapUS()` | **`andThen foreach`** over all 50 states + DC → one map per state, distributed across the fleet (national TIGER county file downloads once + cache-shares) |
| `census.Vulnerability.BuildNationalIndex(title)` | Scan `output/svi/<state>/` → write `output/svi/index.html`, a sortable table linking every state map with its most-vulnerable county + median county poverty (reads the tiny `svi-summary.json` sidecars BuildSVIMap writes — KB, not the full geojsons) |
| `census.workflows.BuildNationalSVIIndex()` | Wraps `BuildNationalIndex` as a runnable workflow so the index path is a tracked result |

**Clickable in the dashboard.** Any `.html` result attribute (each state's
`html_path`, the national `index_path`) renders an **"Open map"** button on the
run's detail page — the dashboard serves it from MinIO via `/output/raw/…`, and
the national index's relative links to each state map resolve under the same
path. So a `BuildNationalSVIIndex` run gives you a one-click browseable national
map straight from the UI.

```bash
# one state
fw ffl run --primary src/census_us/ffl/census.ffl \
  $(for f in $(find src/census_us -name '*.ffl' ! -name census.ffl); do echo --library $f; done) \
  --workflow census.workflows.BuildVulnerabilityMap \
  --inputs '{"state_fips":"56","state_name":"Wyoming"}' --task-list census

# all 50 states + DC, then the national index
fw ffl run ... --workflow census.workflows.BuildVulnerabilityMapUS --task-list census
fw ffl run ... --workflow census.Vulnerability.BuildNationalIndex --task-list census
```

> **Requires `CENSUS_API_KEY`** — the ACS5 API returns an empty body without it.
> The downloader appends it to the request (never the cached/returned URL).

## Required infrastructure

| Service | Purpose |
|---------|---------|
| MongoDB | Facetwork registry + workflow state, plus `census_acs_*`, `census_tiger_*`, `census_summary_*` collections for ingested data |

The handlers fall back gracefully when `requests` or `pymongo` aren't
installed — useful for offline tests and partial-pipeline runs.

## Layout

```
fwh_census_us/
├── pyproject.toml                  # facetwork.examples entry point
├── README.md
├── CLAUDE.md                       # guidance for Claude Code in this repo
├── USER_GUIDE.md                   # human-facing walkthrough
├── agent-spec/                     # tools-pattern, cache-layout specs
├── conftest.py                     # pytest fixtures
├── tests/                          # repo-level integration tests
└── src/census_us/
    ├── __init__.py                 # exports `example: ExamplePackage`
    ├── handlers/                   # 6 event-facet subpackages
    │   ├── acs/                    # ACS demographic extraction
    │   ├── downloads/              # raw HTTP downloads (ACS + TIGER)
    │   ├── ingestion/              # 15 MongoDB upsert handlers
    │   ├── summary/                # state rollups + geo joins
    │   ├── tiger/                  # TIGER county geometry
    │   ├── vulnerability/          # SVI compute + choropleth (BuildSVIMap, BuildNationalIndex)
    │   └── shared/census_utils.py  # shim into tools/_lib
    ├── ffl/                        # top-level + per-domain FFL workflows
    └── tools/                      # CLI utilities + _lib/ (real impl)
        ├── _lib/                   # downloader, acs/tiger extractors, db ingest, summary builder,
        │                          #   svi (SVI + national index), storage (s3/local-aware)
        ├── *.py                    # one CLI per major operation
        └── *.sh                    # shell wrappers
```

## License

Apache 2.0 — see `LICENSE`.

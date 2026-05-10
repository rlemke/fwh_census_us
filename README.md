# census-us

A standalone [Facetwork](https://github.com/rlemke/facetwork) example package
providing FFL workflows and handlers for working with US Census Bureau data:

- **ACS demographics** — pull American Community Survey variables (population, income, education, housing, commuting, tenure, age, vehicles, race, poverty, employment, …) via the Census REST API
- **TIGER shapefiles** — fetch county / tract geometry from the TIGER/Line endpoint
- **MongoDB ingestion** — upsert per-state ACS variables and county geometry into `census_*` collections
- **Per-state summaries** — compute state-level rollups + join census variables to TIGER county geometry for choropleth visualization
- **Dashboard map** — county-level choropleth in Facetwork's dashboard with switchable variables (density, income, education, commuting, …)

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
    ├── handlers/                   # 5 event-facet subpackages
    │   ├── acs/                    # ACS demographic extraction
    │   ├── downloads/              # raw HTTP downloads (ACS + TIGER)
    │   ├── ingestion/              # 15 MongoDB upsert handlers
    │   ├── summary/                # state rollups + geo joins
    │   ├── tiger/                  # TIGER county geometry
    │   └── shared/census_utils.py  # shim into tools/_lib
    ├── ffl/                        # top-level + per-domain FFL workflows
    └── tools/                      # CLI utilities + _lib/ (real impl)
        ├── _lib/                   # downloader, acs/tiger extractors, db ingest, summary builder
        ├── *.py                    # one CLI per major operation
        └── *.sh                    # shell wrappers
```

## License

Apache 2.0 — see `LICENSE`.

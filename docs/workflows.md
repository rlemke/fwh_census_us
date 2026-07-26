# Orchestration workflows

**Namespace:** `census.workflows` ·
**FFL:** `src/census_us/ffl/census.ffl` (774 lines — the top-level entry points) ·
**Composes:** every other namespace (`Operations`, `ACS`, `TIGER`, `Summary`, `Ingestion`, `Vulnerability`, `Publish`) ·
**Tests:** `tests/test_national_county_map.py`, `tests/test_indicators_and_time_maps.py`, `tests/test_catalog_manifest.py`

## Overview

The domain's front door: the entry-point workflows that wire downloads → extracts →
join → render → publish into runnable pipelines. Two shapes dominate — the
**state-analysis** family (`AnalyzeState*`, the tabular/DB path) and the **map**
family (`Build*MapUS`, the choropleth path), the latter being what census-us is best
known for. This is the primary narrative for how the tiers fit together; the
per-feature specs cover the pieces.

## How it works

Workflows are `andThen` blocks composing facets from the other namespaces. Two
canonical structures:

- **Linear per-state:** `AnalyzeState` downloads ACS (+ detailed) + TIGER, runs ~14
  `Extract*` in parallel off the cached files, `JoinGeo`s them onto county geometry,
  `SummarizeState`s, and `yield`s the summary. `AnalyzeStateWithDB` adds the 15
  `*ToDB` ingests (see [ingestion](ingestion.md)).
- **Fan-out families:** `andThen foreach st in $.states` (50 states + DC, embedded as
  a default `Json` list of `{fips, name}`) or `andThen foreach mp in $.maps` (per
  metric). Each iteration is a distributed task; the runtime spreads them across the
  fleet.

## Fan-out

The heart of the spec — two deliberate axes:

- **Fan out over states** (per-state maps): `BuildVulnerabilityMapUS`,
  `BuildStateMetricsMapUS` run one `BuildVulnerabilityMap` / `BuildStateMetricsMap` per
  state. The national TIGER county file downloads **once** and cache-shares; ACS pulls
  are per-state. Each per-state build is itself collapsed to a single
  `BuildStateMetrics` task (not a 14-facet sub-chain) to avoid wedging runners on
  redundant MinIO localizes.
- **Fan out over metrics** (national maps): `BuildCountyMapsUS`, `BuildCountyTimeMapsUS`,
  `BuildHealthTimeMapsUS` run `andThen foreach mp in $.maps`, and **every iteration
  reuses the same two cached national downloads** (`for=county:*` returns all ~3,200
  counties in one call) — so geography is single-task and only the metric varies.

Single-map workflows (`BuildIncomeMapUS`, `BuildCrimeMapsUS`, `BuildJoblessTimeMapUS`,
`BuildOverdoseTimeMapUS`, …) are one or two render tasks over shared downloads.

## Data & fields

- **State list:** an embedded default `Json` of 51 `{fips, name}` objects (`#{…}`
  literals) — the 50 states + DC.
- **Metric lists:** embedded `{metric, title, region}` (or `+note`) defaults; the
  `metric` values must be [metric-registry](metrics-registry.md) keys.
- **Standard results:** `status`, `html_path` / `index_path` / `pages_url` (clickable
  in the dashboard), and a `detail` string (e.g. "N of M counties with data").

## External libraries / binaries

None directly — workflows are pure FFL composition. The dependencies live in the
facets they call (see the per-namespace specs).

## Facets & workflows

Selected entry points (all in `census.workflows`):

| Workflow | Shape | Purpose |
|---|---|---|
| `AnalyzeState(state_fips, state_name)` | linear | download→extract→join→summary for one state |
| `AnalyzeStateWithDB(...)` | linear + ingest | as above, persisted to MongoDB |
| `AnalyzeStates_03()` | 3-way | parallel-analysis demo (AL/AK/AZ) |
| `BuildVulnerabilityMap[US]` / `BuildNationalSVIIndex` | per-state fan-out + index | SVI maps (see [svi](svi.md)) |
| `BuildStateMetricsMap[US]` / `BuildRankings` / `BuildMetricsMapsIndex` | per-state fan-out | multi-metric state maps + national rankings |
| `BuildIncomeMapUS` / `BuildCountyMapsUS` / `BuildCountyTimeMapsUS` | per-metric | national county (time) choropleths |
| `BuildCrimeMapsUS` / `BuildMortalityMapsUS` / `BuildHealthTimeMapsUS` | mixed | CHR/CDC/NCI indicator + time maps |
| `BuildJoblessTimeMapUS` / `BuildOverdoseTimeMapUS` / `BuildSuicideTimeMapUS` / `BuildHomelessTimeMapUS` / `BuildHomeValueTimeMapUS` / `BuildElectionTimeMapUS` / `BuildUnauthorizedTimeMapUS` | single wide-CSV time map | one external series each |
| `PublishStatsSite` / `PublishToSite` | publish | push bundles to GitHub Pages ([publish](publish.md)) |

The three `AnalyzeState*` workflows are the catalog-indexed entry points
(`catalog.yaml`, matched by `fw_catalog_match`).

## Cache / output

Workflows write nothing themselves; their `yield`ed results carry the paths their
facets wrote (MinIO on the fleet), surfaced as dashboard "Open map" buttons.

## Gotchas & notes

- **Relative `$`-scoping.** Steps reference `$.state_fips` (workflow params) and
  `foreach` variables as `$.st.fips` / `$.mp.metric`; sibling steps by name
  (`acs.file`, `map.html_path`). This matches the platform's relative-scoping model.
- **National downloads are shared, not re-fetched.** The per-metric fan-outs each
  declare the same `DownloadACS`/`DownloadTIGER` steps; the cache-first downloaders
  mean only the first iteration hits the network.
- **Approximation disclosures ride through the workflow.** The crime/health/mortality/
  homeless/unauthorized workflows pass a `source_note` into the map — it's the honest
  provenance label; keep it.
- **`metric` values must be registry keys** or the render facet raises `Unknown metric`.

## Related specs

- [downloads](downloads.md), [acs-extraction](acs-extraction.md), [tiger-geometry](tiger-geometry.md) — the ingest/extract steps.
- [summary-and-join](summary-and-join.md), [metrics-registry](metrics-registry.md) — the transform tier.
- [choropleth-maps](choropleth-maps.md), [svi](svi.md) — the render tier the map families drive.
- [ingestion](ingestion.md), [publish](publish.md) — the persist/publish tails.

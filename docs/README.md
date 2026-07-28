# census-us — Feature Specifications

This directory holds one **spec per census-us feature**. Each document follows a
common shape ([`SPEC_TEMPLATE.md`](SPEC_TEMPLATE.md)) and states, for that feature:
how it works, whether and how it **fans out** across the fleet, the **ACS
tables / TIGER layers / external sources** and the concrete **columns and GEOID/FIPS
keys** it reads, the **external libraries/binaries** it relies on, its **facets &
workflows**, and its **cache/output**. Claims are grounded in the FFL `/** … */`
docstrings, the handler code, and the `tools/_lib/` implementation — the source of
truth for each facet remains its FFL docstring; these specs are the feature-level
narrative over them.

**Start here:** [**Choropleth map engine**](choropleth-maps.md) — the flagship
capability (national county maps, time maps, per-state metric maps, rankings), all
driven by the shared [metric registry](metrics-registry.md). For how the tiers wire
together end-to-end, read [**Orchestration workflows**](workflows.md).

## Cross-cutting

| Spec | What it covers |
|------|----------------|
| [workflows.md](workflows.md) | The entry-point workflows: the `AnalyzeState` (tabular/DB) family and the `Build*MapUS` map families; the two fan-out axes (per-state vs per-metric) and shared cached downloads. |
| [metrics-registry.md](metrics-registry.md) | The single source of truth (`_lib/metrics.py`) for every indicator — `num/den`/`raw`/`invert`, `worse` direction, `in_svi`, `national_only`. Drives the SVI, state maps, national maps, and rankings. |
| [storage-and-cache.md](storage-and-cache.md) | The `FW_STORAGE`-aware cache/output wrapper (`cstore`): `cache_root()`/`output_root()`, `join`, stage-then-finalize writes, localize-before-read — one code path, local or MinIO. |

## Data ingest & sources

| Spec | What it covers |
|------|----------------|
| [downloads.md](downloads.md) | `census.Operations` — ACS REST API + TIGER ZIP downloads, and the external county/state indicator + wide-time series (CHR, CDC, NCI, HUD, Pew, Zillow, elections). Cache-first; the 50-var cap; `CENSUS_API_KEY`. |
| [acs-extraction.md](acs-extraction.md) | `census.ACS` — slice one ACS table's columns out of a downloaded CSV (15 `Extract*` facets, facet → table_id map). |
| [tiger-geometry.md](tiger-geometry.md) | `census.TIGER` — TIGER/Line shapefile ZIP → GeoJSON polygons (county/state/tract/BG/place) via fiona/pyshp; the `GEOID` vs `GEOIDFQ` field. |

## Transform & discovery

| Spec | What it covers |
|------|----------------|
| [summary-and-join.md](summary-and-join.md) | `census.Summary` — `JoinGeo` (ACS onto county geometry, the `_norm_geoid` fix + derived metrics) and `SummarizeState`. |
| [vocab.md](vocab.md) | `census.Vocab` — pure NL indicator → ACS `table_id` + columns resolution (the only `pure`/`free` facets). |

## Visualization

| Spec | What it covers |
|------|----------------|
| [choropleth-maps.md](choropleth-maps.md) | **Flagship.** The `census.Vulnerability` render engine — national county maps, year-slider time maps, per-state multi-metric maps, national rankings; MapLibre HTML, quantile scales, the one-task `BuildStateMetrics` collapse. |
| [svi.md](svi.md) | The Social Vulnerability Index compute path — 6-indicator percentile composite + national index; the age-in-join caveat; within-state vs cross-state comparability. |

## Persistence & publish

| Spec | What it covers |
|------|----------------|
| [ingestion.md](ingestion.md) | `census.Ingestion` — 15 `*ToDB` MongoDB upserts (idempotent `(dataset_key, feature_key)` index); used only by `AnalyzeStateWithDB`. |
| [publish.md](publish.md) | `census.Publish` — push output bundles to a GitHub Pages repo; the token gate + `ModuleNotFoundError` release that pins publishing to the credentialed host. |
| [ffl-examples.md](ffl-examples.md) | **Usage patterns.** A gallery of complete, compile-checked FFL examples over these facets — one download → parallel extracts, array args into `JoinGeo`, state `foreach`, `PublishWebBundle`, `when` guards, mixins + `catch`. |

---

*See also the machine-readable capability index at
[`src/census_us/catalog.yaml`](../src/census_us/catalog.yaml) (workflows + facets by
intent, loaded via `census_us.catalog.load_manifest()`), the repo
[`CLAUDE.md`](../CLAUDE.md) (domain contract + gotchas), the
[`USER_GUIDE.md`](../USER_GUIDE.md), and the `agent-spec/` design specs. The
live/queryable interface is the MCP `fw_capabilities` / `fw_catalog_match` /
`fw_describe_handler` tools.*

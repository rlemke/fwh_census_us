# Social Vulnerability Index (SVI)

**Namespace:** `census.Vulnerability` ·
**FFL:** `src/census_us/handlers/vulnerability/ffl/census_vulnerability.ffl` ·
**Handlers:** `src/census_us/handlers/vulnerability/svi_handlers.py` (`handle_build_svi_map`, `handle_build_national_index`) ·
**Impl:** `src/census_us/tools/_lib/svi.py` (+ `metrics.py`)

## Overview

A county-level **Social Vulnerability Index** choropleth: a CDC/ATSDR-style
6-indicator composite scored per county and rendered as a MapLibre map, plus a
national index page linking a per-state fan-out. It answers "which counties are most
socially vulnerable" from the same download→extract→join chain the rest of the
domain uses — `BuildSVIMap` reads a `JoinGeo` output GeoJSON and needs no new
ingestion.

## How it works

`build_svi_map(joined_path, region, title)` (svi.py):

1. Read the joined county GeoJSON (TIGER geometry + raw ACS columns).
2. For each county compute the SVI indicator values via the **metric registry**
   (`metrics.SVI_METRICS`, i.e. the `in_svi=True` metrics), all oriented "higher =
   more vulnerable".
3. **Percentile-rank** each indicator across the counties in the input
   (`_percentile_ranks`, average-rank for ties, in `[0,1]`); a single county gets a
   neutral 0.5.
4. The county SVI is the **mean of its available indicator percentiles** (counties
   missing an indicator use the rest; counties missing everything render grey).
5. Render a YlOrRd choropleth (`_RAMP`) shaded by SVI percentile, with a per-county
   click popup showing every component, and write the SVI GeoJSON + HTML.

`build_national_index(title)` scans `output/svi/<state>/` and writes
`output/svi/index.html` — a sortable table linking each state's map with its
most-vulnerable county and the (nationally comparable) **median county poverty
rate**, read from the tiny `svi-summary.json` sidecars `build_svi_map` writes (KB,
not the full GeoJSONs).

## Fan-out

**`BuildSVIMap` is single-task per state.** The nationwide picture comes from the
`census.workflows.BuildVulnerabilityMapUS` workflow, which runs
`BuildVulnerabilityMap` `andThen foreach st in $.states` (50 + DC) — one distributed
task per state, national TIGER county file downloaded once + cache-shared, ACS pulls
per-state. `BuildNationalIndex` then stitches the results (single-task, reads the
sidecars). See [workflows](workflows.md).

## Data & fields

- **The 6 SVI indicators** (`metrics.SVI_METRICS` where `in_svi=True`, all `worse=high`):
  `poverty` (B17001_002E/_001E), `unemployment` (B23025_005E/_003E), `no_bachelors`
  (100 − B15003 bachelor's-plus/_001E), `elderly` (B01001 65+ bands/_001E),
  `no_vehicle` (B25044 no-vehicle cells/_001E), `renter` (B25003_003E/_001E). (The
  registry also flags `less_than_hs`, `hs_only`, `snap`, `uninsured`, `gini` as
  `in_svi`; the canonical 6-indicator variant is the CDC SES/demographic subset —
  see the `svi.py` module docstring.)
- **Percentiles are within-input.** Ranks are computed across the counties present,
  so SVI percentiles are comparable *within a state* but **not across states**; the
  national index instead ranks states by a nationally comparable **raw** poverty rate.
- **Output schema (`BuildSVIMap`):** `svi_path, html_path, county_count,
  scored_count, region`.

## External libraries / binaries

- **MapLibre GL** from the unpkg CDN (browser-side; needs internet at view time).
- Registry-driven compute is pure Python (`metrics.compute_metric`); no geometry libs
  in the SVI path itself (geometry arrives already-joined from
  [summary-and-join](summary-and-join.md)).
- `attribution.py` / `mapsearch.py` for the footer + county search, shared with the
  [choropleth-maps](choropleth-maps.md) engine.

## Facets & workflows

| Facet | Effect/Cost | Purpose |
|---|---|---|
| `BuildSVIMap(joined_path, region="state", title="Social Vulnerability Index")` | io / cheap | compute SVI + render choropleth for one input's counties |
| `BuildNationalIndex(title)` | io / cheap | scan per-state SVI maps → national index page |

Driven by `census.workflows.BuildVulnerabilityMap` (one state end-to-end, **includes
age** in the join), `BuildVulnerabilityMapUS` (national fan-out), and
`BuildNationalSVIIndex` (wraps `BuildNationalIndex`).

## Cache / output

SVI GeoJSON + HTML + `svi-summary.json` sidecar under `output_root()/svi/<region>/`;
the national index at `output_root()/svi/index.html` (MinIO on the fleet). The
`.html`/`index.html` results are clickable "Open map" buttons in the dashboard, and
the index's relative links to each state map resolve under the same `/output/raw/`
path.

## Gotchas & notes

- **Use `BuildVulnerabilityMap`, not `AnalyzeState`, as the upstream join.**
  `AnalyzeState` omits the B01001 age extract from its join, so the SVI's 65+
  indicator would be blank; `BuildVulnerabilityMap` adds age explicitly.
- **Within-state percentiles ≠ cross-state.** Do not compare two states' SVI shades
  directly; the index uses raw poverty for cross-state ranking for exactly this reason.
- **CDC theme 4 (race/ethnicity) is intentionally omitted** from this 6-indicator
  variant; race is in the join if a future 4-theme variant wants it.

## Related specs

- [choropleth-maps](choropleth-maps.md) — the shared map-rendering engine.
- [metrics-registry](metrics-registry.md) — defines the `in_svi` indicator set.
- [summary-and-join](summary-and-join.md) — produces the joined GeoJSON input (age caveat).
- [workflows](workflows.md) — the per-state fan-out + national index.

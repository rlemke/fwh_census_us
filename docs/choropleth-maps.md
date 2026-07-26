# Choropleth map engine

**Namespace:** `census.Vulnerability` (the render facets) ·
**FFL:** `src/census_us/handlers/vulnerability/ffl/census_vulnerability.ffl` ·
**Handlers:** `src/census_us/handlers/vulnerability/svi_handlers.py` ·
**Impl:** `src/census_us/tools/_lib/maps.py` (+ `metrics.py`, `mapsearch.py`, `attribution.py`, `indicators.py`) ·
**Tests:** `tests/test_national_county_map.py`, `tests/test_indicators_and_time_maps.py`

## Overview

**The flagship capability.** This is the rendering engine that turns joined
county/state data into self-describing MapLibre choropleth HTML — the national
county maps the domain is known for (income, poverty, education, crime, health,
mortality, home value, elections, …), their year-slider time-map variants, the
per-state multi-metric maps, and the national state-rankings page. Every map is
driven by the shared **[metric registry](metrics-registry.md)**, so adding a metric
adds a map without touching the renderer.

Despite living in the `census.Vulnerability` namespace (historically the SVI came
first), most of these facets are general choropleth builders. The SVI-specific
compute path is documented separately in [svi](svi.md); this spec covers the
map-rendering machinery they all share.

## How it works

The renderers in `maps.py` share a pattern: read source rows → look up a metric in
`metrics.BY_KEY` → compute one value per county via `metrics.compute_metric` → attach
`{GEOID, NAME, val, rank}` to each TIGER polygon → derive **quantile** color stops
(national distributions are right-skewed, so linear min→max would wash out) → emit a
single HTML file with the geometry inlined and a MapLibre map + legend + side panel.

Key builders:

- **`build_national_county_map(acs_path, tiger_path, detail_path=, metric=, …)`** —
  one national county choropleth for one ACS registry metric. Merges the optional
  detailed (age) batch per county, computes the metric, ranks counties (1 = best by
  the metric's `worse` direction), builds quantile stops, and attaches a **highest-20 /
  lowest-20 side panel** (each entry carries a centroid so a click flies the map there).
  Counties in TIGER but absent from ACS (territories, suppressed values) shade grey.
- **`build_national_county_time_map(...)`** — a year-slider + play map. Values come
  either from per-vintage ACS pulls (`acs_timeseries_values(metric, start, end)`,
  one cached national request per 5-year vintage; `TS_METRIC_START` clamps education/
  unemployment to 2012) or from a precomputed wide `y####` CSV (`wide_csv_values` —
  the CHR/HUD/Zillow/election series). Pooled quantile shading is comparable across
  years; the popup carries per-county history.
- **`build_state_metrics(...)`** — the one-task per-state build: given the 4–5
  downloaded files, extract every table (each CSV localized **once**), join onto
  geometry, and render the per-state multi-metric map. Collapses what used to be a
  14-facet fan-out chain into a single handler (see gotchas).
- **`build_metrics_map(joined_path, …)`** — per-state multi-metric choropleth with a
  dropdown over all registry metrics + the SVI (shaded "dark = worse"); also writes a
  `metrics-summary.json` the rankings consume.
- **`build_national_rankings(...)`** — reads every state's `metrics-summary.json` + a
  state-level income/Gini pull, joins onto TIGER state geometry, writes a sortable
  rankings table + a national state choropleth per metric.
- **`build_metrics_index` / `build_national_index`** — index pages linking the
  per-state maps (the latter is SVI-specific; see [svi](svi.md)).

## Fan-out

Two regimes, deliberately:

- **National maps are single-task.** `for=county:*` returns all ~3,200 counties in
  one API call and the national TIGER file is one download, so each national map is a
  single render task; the map *families* fan out over **metrics** (`andThen foreach mp
  in $.maps`), not geography — every iteration shares the same two cached downloads.
- **Per-state maps fan out over states.** `BuildStateMetricsMapUS` /
  `BuildVulnerabilityMapUS` run `andThen foreach st in $.states` (50 + DC), one
  distributed task per state. `BuildStateMetrics` is the *anti*-fan-out move within a
  state — one task instead of 14 — after the naive chain wedged runners on redundant
  MinIO localizes. See [workflows](workflows.md).

## Data & fields

- **Metric definitions:** entirely in [metrics-registry](metrics-registry.md)
  (`num/den`/`raw`, `worse` direction, `fmt`, `in_svi`, `national_only`).
- **Per-feature props written by the renderer:** `{GEOID (bare FIPS), NAME, val,
  rank}` (national) or the full metric set (per-state dropdown maps). County FIPS is
  taken from `GEOID` or `STATEFP+COUNTYFP`.
- **Color:** the `_RAMP` YlOrRd stops, reversed for `worse == "low"` metrics
  (income/life-expectancy so darker = worse), `ELECTION_STOPS` for `party_margin`
  (fixed diverging red↔blue), quantile-placed against the sorted values.
- **`source_note`** flows from the workflow through to the map's description / "About
  this data" popup verbatim (the provenance/approximation disclosure).

## External libraries / binaries

- **MapLibre GL JS/CSS** — loaded **from the unpkg CDN**
  (`maplibre-gl@4.7.1`) in the emitted HTML. The map HTML is otherwise
  self-contained (geometry inlined) but **needs internet at view time** for the map
  library. (Not a Python dependency.)
- **`fiona`/`pyshp`** (pip, `[shapefiles]`) — via the TIGER reader for geometry.
- **`requests`/`openpyxl`** — only on the `_national_only` external-source paths (the
  indicator/time CSVs are built in [downloads](downloads.md)).
- `attribution.py` adds an inline provenance footer + "About this data" modal linking
  the FFL source on GitHub; `mapsearch.py` builds the searchable county list.

## Facets & workflows

All event facets in `census.Vulnerability`, all render to HTML:

| Facet | Effect/Cost | Purpose |
|---|---|---|
| `BuildNationalCountyMap(acs_file, tiger_file, detail_file, metric, title, region, year)` | io / moderate / 10m | one national county map for one ACS metric |
| `BuildNationalIndicatorMap(tiger_file, indicators_file, metric, title, region, source_note)` | io / moderate / 10m | snapshot national map from a normalized indicator CSV (CHR/NCI) |
| `BuildNationalCountyTimeMap(tiger_file, metric, start_year, end_year, …)` | external / expensive / 20m | year-slider map from per-vintage ACS pulls |
| `BuildNationalSeriesTimeMap(tiger_file, ts_file, metric, …, unit="county")` | io / moderate / 10m | year-slider map from a precomputed wide `y####` CSV |
| `BuildStateMetrics(acs_file, detail_file, social_file, tiger_file, demo_file, state_fips, state_name)` | io / cheap / 10m | one-task per-state extract+join+render |
| `BuildMetricsMap(joined_path, region, title)` | io / cheap | per-state multi-metric dropdown map + `metrics-summary.json` |
| `BuildNationalRankings(title)` | io / cheap | state rankings table + per-metric national state choropleths |
| `BuildMetricsIndex(title)` / `BuildNationalIndex(title)` | io / cheap | index pages linking per-state maps |

Driven by the `census.workflows.Build*` workflows ([workflows](workflows.md)).

## Cache / output

HTML + inline/companion GeoJSON under `output_root()/national/<region>/…`,
`output_root()/metrics/<state>/…`, `output_root()/svi/<state>/…`,
`output_root()/rankings/…` (MinIO on the fleet). A `.html` result attribute renders
an "Open map" button on the dashboard run page; the published copies go to GitHub
Pages via [publish](publish.md).

## Gotchas & notes

- **Maps need the CDN at view time.** MapLibre is pulled from unpkg — an air-gapped
  viewer sees no basemap. Geometry and data are inlined, so only the library is remote.
- **The 14-facet fan-out wedged the fleet.** The per-state metrics path was
  intentionally collapsed into the single `BuildStateMetrics` handler because the
  chained `Download→Extract×N→Join→Render` fan-out repeatedly re-localized the same
  MinIO objects and starved runners. Prefer the one-task builder for per-state work.
- **Quantile, not linear, color scale.** National income/home-value/etc. are
  right-skewed; linear stops wash out everything below the outliers. Stops are placed
  at value quantiles and forced strictly ascending.
- **`national_only` metrics never appear on state maps.** Their source columns
  (CHR/CDC/HUD/Zillow/election) exist only in the normalized national CSVs, not in the
  per-state joined GeoJSON — the registry flag keeps them off the state dropdowns.
- **Approximation disclosures are load-bearing.** Homeless (CoC apportioned), Pew
  unauthorized (estimates), model-smoothed CDC series — each map's `source_note` says
  so; don't strip it.

## Related specs

- [metrics-registry](metrics-registry.md) — the single source of truth these renderers read.
- [svi](svi.md) — the SVI compute path sharing this engine.
- [summary-and-join](summary-and-join.md) — produces the per-state joined GeoJSON input.
- [downloads](downloads.md) — the national ACS/TIGER pulls + external indicator/time CSVs.
- [workflows](workflows.md) — the map families that drive these facets.
- [publish](publish.md) — pushes the rendered maps to GitHub Pages.

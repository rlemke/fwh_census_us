# Summary & geographic join

**Namespace:** `census.Summary` ·
**FFL:** `src/census_us/handlers/summary/ffl/census_summary.ffl` ·
**Handlers:** `src/census_us/handlers/summary/summary_handlers.py` ·
**Impl:** `src/census_us/tools/_lib/summary_builder.py` ·
**CLI:** `src/census_us/tools/join-geo.sh`

## Overview

The stitch tier — where the tabular ACS extracts meet the TIGER polygons.
`JoinGeo` merges one-or-more ACS CSVs onto county geometry (keyed on `GEOID`),
computes population density and a set of derived percentage metrics, and writes a
single choropleth-ready GeoJSON. `SummarizeState` is the lighter, geometry-free
sibling: it rolls several `ACSResult`s into one state-level summary JSON. Getting
the GEOID normalization right here is the single most load-bearing detail in the
whole domain.

## How it works

**`join_geo(acs_path, tiger_path, join_field="GEOID", extra_acs_paths=[])`:**

1. Load the primary ACS CSV into a dict keyed by `_norm_geoid(row[GEOID])`, then
   merge each `extra_acs_paths` CSV into the same dict (later columns
   `dict.update` onto the same county).
2. Load the TIGER GeoJSON. For each feature, `_norm_geoid(props[GEOID])` and, on a
   hit, `props.update(acs_row)` — so every ACS estimate column lands on the polygon.
3. Compute `population_density_km2` from TIGER `ALAND` (m² → km²) and ACS
   `B01003_001E`, then `_compute_derived_metrics(props)` for friendly aliases
   (`population`, `median_income`, `housing_units`) and ratio metrics
   (`pct_below_poverty`, `unemployment_rate`, `pct_owner/renter_occupied`,
   `pct_bachelors_plus`, `pct_white/black/asian`, `pct_drove_alone`,
   `pct_public_transit`, `vehicles_per_household`).
4. Write the enriched `FeatureCollection` to
   `output_root()/joined/<acs-stem>_<tiger-stem>_joined.geojson`.

**`summarize_state(...)`** collects population/income/housing/education/commuting
(+ optional race/poverty/employment) `ACSResult`s, derives the state FIPS from an
output-path stem, sums record counts and tables-joined, and writes
`output_root()/summary/<fips>_summary.json`. It is **not** a geographic join — no
geometry, no per-county rows.

## Fan-out

**Single-task.** One join per state (or one national join). Fan-out lives in the
workflows that call it per state.

## Data & fields

- **Join key:** `GEOID`, normalized by `_norm_geoid` — splits on `"US"` so ACS
  `0500000US56023` and TIGER `56023` both collapse to `56023`.
- **Inputs:** primary ACS CSV (`pop`), `extra_acs_paths` (income, education, tenure,
  vehicles, poverty, employment, age, …), TIGER county GeoJSON.
- **Derived fields written** (`_compute_derived_metrics`, `_safe_pct`): the friendly
  aliases + the `pct_*` ratios above, guarding against missing/zero denominators
  (returns `None`, not a divide error). `pct_renter_occupied = 100 − pct_owner_occupied`.
- **`SummarizeState` output:** `CensusSummary` (`state_fips, state_name, output_path,
  tables_joined, record_count`); the JSON carries a per-table breakdown.

## External libraries / binaries

None beyond stdlib `csv`/`json` and the `_lib.storage` wrapper. Pure I/O + arithmetic.

## Facets & workflows

- `JoinGeo(acs_path, tiger_path, join_field="GEOID", extra_acs_paths=[]) =>
  (result: CensusSummary)` — event, `with Effect(kind = "io")`, `with Cost(tier = "cheap")`.
  (Note: the handler returns `record_count = feature_count` and blank
  state fields; `tables_joined` is reported as `1`.)
- `SummarizeState(population, income, housing, education, commuting, race=null,
  poverty=null, employment=null) => (result: CensusSummary)` — event, io/cheap.

Both are consumed by `census.workflows.AnalyzeState[WithDB]`; `JoinGeo` also feeds
every per-state map (its output GeoJSON is the `joined_path` the SVI / metrics
renderers read).

## Cache / output

Joined GeoJSON under `output_root()/joined/…`; state summary JSON under
`output_root()/summary/…` (MinIO on the fleet). Both are read back by downstream
renderers and by [ingestion](ingestion.md).

## Gotchas & notes

- **The GEOID mismatch is the classic bug.** Join the two raw `GEOID` fields
  directly and *every* ACS column silently fails to merge — you get a geometry-only
  GeoJSON and a blank map. `_norm_geoid` on **both** sides is mandatory; TIGER's
  prefixed form lives in `GEOIDFQ`, not `GEOID`.
- **`AnalyzeState` omits age from the join.** Its `extra_acs_paths` list does not
  include the B01001 age extract, so an SVI built off an `AnalyzeState` join would be
  missing its 65+ indicator — `BuildVulnerabilityMap` adds age explicitly for exactly
  this reason (see [svi](svi.md)).
- **Missing denominators return `None`, never 0 or an error** (`_safe_pct`) — a
  county with no poverty universe drops out of that metric rather than skewing it.

## Related specs

- [acs-extraction](acs-extraction.md) / [tiger-geometry](tiger-geometry.md) — the two inputs.
- [metrics-registry](metrics-registry.md) — the derived metrics computed on the joined props.
- [svi](svi.md), [choropleth-maps](choropleth-maps.md) — consume the joined GeoJSON.
- [ingestion](ingestion.md) — persists the joined + summary outputs.
- [workflows](workflows.md) — `AnalyzeState` orchestrates the join.

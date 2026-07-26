# TIGER geometry extraction

**Namespace:** `census.TIGER` ·
**FFL:** `src/census_us/handlers/tiger/ffl/census_tiger.ffl` ·
**Handlers:** `src/census_us/handlers/tiger/tiger_handlers.py` ·
**Impl:** `src/census_us/tools/_lib/tiger_extractor.py` ·
**CLI:** `src/census_us/tools/tiger-extract.sh`

## Overview

The geometry half of the pipeline: read a downloaded TIGER/Line shapefile ZIP and
write GeoJSON polygons for a geography level (county, state, tract, block group,
place), optionally filtered to one state. These polygons are the canvas every
choropleth is painted on — the join ([summary-and-join](summary-and-join.md))
enriches each feature with ACS attributes keyed on `GEOID`.

## How it works

`extract_tiger(zip_path, geo_level, state_fips, year)` (tiger_extractor.py):

1. Resolve `geo_level` in `_GEO_CONFIG` → the file suffix + the FIPS field to filter
   on. COUNTY/TRACT/BG/PLACE filter on `STATEFP`; **STATE has `fips_field=None`** so
   the national state file keeps all 50 states + DC (no per-state filter).
2. `cstore.localize()` the cached ZIP to a real local file (shapefile readers need a
   path, not an `s3://` URI), then read features through the first available reader:
   **fiona** → **pyshp** → a `.geojson`-inside-ZIP fallback.
3. Keep features where `_match(props, fips_field, state_fips)` holds, and write a
   `FeatureCollection` to `output_root()/tiger/<geo>/<state>_<geo>.geojson`.

The handler (`tiger_handlers.py`) maps facet → geo level via `_FACET_GEO_MAP`
(`ExtractCounties`→COUNTY, `ExtractStates`→STATE, `ExtractTracts`→TRACT,
`ExtractBlockGroups`→BG, `ExtractPlaces`→PLACE) and coerces the `CensusFile.path`
into `extract_tiger`.

## Fan-out

**Single-task per extraction.** COUNTY and STATE come from the *national* TIGER file
(the [download](downloads.md) layer picks `tl_<year>_us_county.zip`), so a national
county map extracts geometry **once** and shares it across every metric iteration —
no per-state geometry fan-out is needed. Per-state maps extract that state's counties
in one pass.

## Data & fields

- **Geography levels** (`_GEO_CONFIG`): COUNTY (`STATEFP` filter), STATE (no filter,
  national), TRACT/BG/PLACE (`STATEFP` filter).
- **Key fields preserved** on each feature's `properties`: TIGER carries the bare
  FIPS in `GEOID` (`"56023"`) — the prefixed form is in `GEOIDFQ` — plus `STATEFP`,
  `COUNTYFP`, `NAMELSAD`/`NAME`, and `ALAND` (land area, used for population density
  at join time). All raw shapefile attributes pass through.
- **Filter mechanism:** a Python `props[STATEFP] == state_fips` predicate (`_match`),
  or no filter for STATE.
- **Output:** `TIGERResult` (`output_path, feature_count, geography_level, year,
  format="GeoJSON", extraction_date`).

## External libraries / binaries

- **`fiona`** (pip; GDAL-backed) — primary shapefile reader (`fiona.open("zip://…")`).
- **`pyshp`** (`import shapefile`, pip, `[shapefiles]` extra) — fallback reader.
- **`shapely`** (pip, `[shapefiles]` extra) — used elsewhere for geometry; the reader
  itself relies on the `__geo_interface__` of pyshp shapes.
- Reader availability is guarded (`HAS_FIONA` / `HAS_PYSHP`); with neither, the ZIP
  `.geojson` fallback runs, and failing all three the output is an **empty**
  FeatureCollection (logged as a warning, not raised).

## Facets & workflows

5 event facets, all `ExtractX(file: CensusFile, state_fips: String) => (result:
TIGERResult)` with `with Effect(kind = "io")`, `with Cost(tier = "cheap")`:
`ExtractCounties`, `ExtractStates` (national, pass `state_fips="us"`),
`ExtractTracts`, `ExtractBlockGroups`, `ExtractPlaces`. `ExtractStates` feeds the
national state rankings/choropleths (see [choropleth-maps](choropleth-maps.md)).

## Cache / output

GeoJSON under `output_root()/tiger/<geo>/…` (MinIO on the fleet). The heavy national
COUNTY file (~3,200 features) is extracted once per run and reused by every metric
map.

## Gotchas & notes

- **`GEOID` here is bare FIPS, not prefixed.** TIGER `GEOID="56023"` vs ACS
  `GEOID="0500000US56023"`. The join normalizes both (see
  [summary-and-join](summary-and-join.md) → `_norm_geoid`); do **not** join the two
  raw fields directly or every ACS column silently fails to merge.
- **Empty output on missing readers is silent-ish.** If neither fiona nor pyshp is
  installed and there's no embedded geojson, you get a valid-but-empty
  FeatureCollection (warning-logged). Install the `[shapefiles]` extra on render hosts.
- **Localize before read.** The readers need a local path; the `_lib.storage` wrapper
  pulls the cached ZIP down from MinIO first — never hand a raw `s3://` path to fiona.

## Related specs

- [downloads](downloads.md) — produces the TIGER ZIP.
- [summary-and-join](summary-and-join.md) — enriches these polygons with ACS data.
- [choropleth-maps](choropleth-maps.md) — renders them (national + per-state).
- [storage-and-cache](storage-and-cache.md) — the localize-before-read contract.

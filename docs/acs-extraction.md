# ACS indicator extraction

**Namespace:** `census.ACS` ·
**FFL:** `src/census_us/handlers/acs/ffl/census_acs.ffl` ·
**Handlers:** `src/census_us/handlers/acs/acs_handlers.py` ·
**Impl:** `src/census_us/tools/_lib/acs_extractor.py` ·
**CLI:** `src/census_us/tools/acs-extract.sh`

## Overview

The transform tier for American Community Survey data: take a downloaded ACS CSV
(a wide file with every requested estimate column) and slice out **one table's
columns** as a per-state, per-geography extract CSV. One facet per demographic
indicator — population, income, housing, education, commuting, tenure, households,
age, vehicles, race, poverty, employment, plus Gini/SNAP/insurance — each pinned to
its ACS table ID. These extracts are the tabular half of the join that produces a
choropleth-ready GeoJSON.

## How it works

`extract_acs_table(csv_path, table_id, state_fips, geo_level)` (acs_extractor.py):

1. Looks up `table_id` in `ACS_TABLES` (the catalogue mapping table → label +
   estimate columns), erroring on an unknown table.
2. Streams the downloaded CSV, keeping rows whose `GEOID` starts with
   `0500000US<state_fips>` (county rows for that state) **and** that carry at least
   one non-empty target column.
3. Writes a slim `GEOID,NAME,<target cols>` CSV to
   `output_root()/acs/<table>/<state>_<geo>_<table>.csv`.

The handler (`acs_handlers.py`) is a thin factory: `_FACET_TABLE_MAP` maps each
facet name to its table ID (`ExtractPopulation`→B01003, `ExtractIncome`→B19013, …),
`_make_acs_handler` builds a dispatch closure per facet, and the same `extract_acs_table`
backs the `acs-extract.sh` CLI. No demographic logic lives in the handler — it's a
coercion layer over `_lib`.

## Fan-out

**Single-task per extraction.** Extracts are fanned *by the workflow* (`AnalyzeState`
runs ~14 `Extract*` in parallel off one downloaded file; `BuildVulnerabilityMapUS`
fans the whole chain per state) — the facet itself is one cheap CSV pass. Note the
per-state metrics path deliberately **collapses** these 14 facets into a single
`BuildStateMetrics` task to avoid redundant MinIO localizes (see
[choropleth-maps](choropleth-maps.md)).

## Data & fields

- **Facet → ACS table** (`_FACET_TABLE_MAP`): `ExtractPopulation` B01003,
  `ExtractIncome` B19013, `ExtractHousing` B25001, `ExtractEducation` B15003,
  `ExtractCommuting` B08301, `ExtractTenure` B25003, `ExtractHouseholds` B11001,
  `ExtractAge` B01001, `ExtractVehicles` B25044, `ExtractRace` B02001,
  `ExtractPoverty` B17001, `ExtractEmployment` B23025, `ExtractGini` B19083,
  `ExtractSnap` B19058, `ExtractInsurance` B27001.
- **Column sets** are in `ACS_TABLES` (acs_extractor.py) — e.g. B15003 keeps the
  full attainment ladder `_001`..`_025E` (needed for less-than-HS, HS-only,
  no-bachelor's, graduate-degree metrics), B27001 keeps `_001E` + the 18
  "no coverage" cells (uninsured rate), B01001 all 49 sex-by-age cells.
- **Filter mechanism:** a `GEOID.startswith("0500000US<fips>")` prefix test — county
  rows only, single state. (Age uses the *detailed* file; the rest use the default
  file.)
- **Output:** `ACSResult` (`table_id, output_path, record_count, geography_level,
  year, extraction_date`).

## External libraries / binaries

None beyond the stdlib (`csv`) and the `_lib.storage` wrapper. No `requests`, no
geometry libs — extraction is pure CSV I/O over an already-downloaded file.

## Facets & workflows

15 event facets, all `ExtractX(file: CensusFile, state_fips: String, geo_level:
String = "county") => (result: ACSResult)` with `with Effect(kind = "io")` and
`with Cost(tier = "cheap")`. `ExtractGini` / `ExtractSnap` / `ExtractInsurance` read
the *social* batch; `ExtractAge` reads the *detailed* batch; the rest read the
default batch. No pure facets. The NL-name → table mapping is the job of
[vocab](vocab.md) (`census.Vocab.ResolveVariable`).

## Cache / output

Extract CSVs land under `output_root()/acs/<table_id>/…` (MinIO on the fleet).
Re-runs overwrite deterministically (path is keyed on state + geo + table).

## Gotchas & notes

- **Empty extract = column not in the download.** Extraction can only slice columns
  the download pulled; if the table's columns weren't in the request's `columns`
  list the extract is empty (this is why the default batch was extended for poverty
  and employment). Fix at the [download](downloads.md) layer.
- **County-scoped.** The `0500000US<fips>` prefix filter means these are county
  extracts for one state; there is no tract/block-group extraction wired despite the
  `geo_level` param (it's carried through, not used as a second filter).
- The extract preserves the raw ACS estimate columns (e.g. `B19013_001E`) verbatim —
  ratios/derived metrics are computed later, at [join](summary-and-join.md) and
  [metric-registry](metrics-registry.md) time, not here.

## Related specs

- [downloads](downloads.md) — produces the ACS CSV this reads.
- [summary-and-join](summary-and-join.md) — merges these extracts onto county geometry.
- [metrics-registry](metrics-registry.md) — turns the raw columns into derived metrics.
- [vocab](vocab.md) — resolves an NL indicator to the table_id these facets extract.

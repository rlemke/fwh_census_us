<!-- SPEC TEMPLATE — every docs/<feature>.md follows this shape so the set reads
consistently. Delete this comment in real specs. Keep sections in this order;
omit a section only if it genuinely does not apply (say so in one line rather
than dropping the heading silently). Ground every claim in the actual FFL
docstrings / handler code / tools / _lib modules — do not invent behaviour.
Census vocabulary to be specific about: ACS table IDs (B19013 median income,
B01003 population, B17001 poverty, B15003 education, B23025 employment,
B01001 sex-by-age, B25003 tenure, B25044 vehicles), estimate columns
(B19013_001E), GEOID / FIPS join keys, TIGER geography levels (COUNTY, STATE,
TRACT, BG, PLACE), metric registry keys (median_income, poverty, no_bachelors,
elderly, …). -->

# <Feature Name>

**Namespace(s):** `census.<Ns>` · **FFL:** `src/census_us/handlers/<dir>/ffl/*.ffl` (or `src/census_us/ffl/census.ffl`) ·
**Handlers:** `src/census_us/handlers/<dir>/*.py` · **Impl:** `src/census_us/tools/_lib/<...>.py` · **CLI:** `src/census_us/tools/<verb>-<noun>.sh` (if any)

## Overview
One or two paragraphs: what this feature is for, the request it answers, and where
it sits in the pipeline (download → extract → join → render → publish, etc.).

## How it works
The algorithm / data flow, step by step. Name the concrete steps and the shape of
the data at each (ACS JSON → CSV → joined GeoJSON → HTML map, TIGER ZIP → GeoJSON,
etc.). Note the tools/handlers/`_lib` split (CLI + FFL handler both call one `_lib`
implementation) where relevant.

## Fan-out
Does it fan out across the fleet? If yes: what is the fan-out unit (per-state /
per-metric / per-map) and which workflow drives it (an `andThen foreach` over what
list), and why it reduces wall-clock. If single-task, say "single-task — no
fan-out" and why (e.g. the Census API serves all ~3,200 counties in one call).

## Data & fields
The ACS tables / TIGER layers / external sources it reads, the concrete columns
and GEOID/FIPS keys, and the output fields it writes. Be specific
(`B19013_001E`, `B17001_002E / B17001_001E`, `GEOID` vs `GEOIDFQ`, `STATEFP`,
`ALAND`). Name the filter/derivation mechanism (a `for=county:*` API clause, a
`STATEFP == state_fips` predicate, a metric-registry `num/den` ratio). If the
feature does no filtering/derivation, say so.

## External libraries / binaries
Every non-stdlib dependency this feature relies on and what for — `requests`
(HTTP), `fiona` / `pyshp` (shapefile reading), `shapely` (geometry), `pymongo`
(ingestion), `PyYAML` (catalog), `openpyxl` (xlsx sources), plus the browser-side
MapLibre GL loaded from a CDN. Distinguish a **pip** dependency (and which
`pyproject` extra it rides — `[mongodb]`, `[shapefiles]`) from a runtime service
(MongoDB, MinIO, a `GITHUB_TOKEN`).

## Facets & workflows
The key event facets and workflows, with signatures and a one-line purpose taken
from the FFL docstrings. Mark event facets (need a handler) vs pure facets, and
note the `with Effect(...)` / `with Cost(...)` / `with Timeout(...)` mixins.

## Cache / output
The cache namespace under the `_lib.storage` roots (`cache_root()` /
`output_root()` → `$FW_DATA_ROOT/cache/census-us/...` on the fleet, local dirs
otherwise) and the artifact(s) + format (ACS CSV / TIGER GeoJSON / joined GeoJSON /
HTML map / JSON summary). Note whether outputs go to local disk, MinIO/S3, MongoDB,
or the published GitHub Pages site.

## Gotchas & notes
Known pitfalls, rate limits, sensitivity/approximation caveats, or non-obvious
constraints (the GEOID join mismatch, the 50-variable ACS request cap, the
`CENSUS_API_KEY` requirement, model-smoothed/approximated series, the CDN
dependency for maps). Worth capturing anything a future maintainer would trip on.

## Related specs
Links to the specs this feature composes with or depends on.

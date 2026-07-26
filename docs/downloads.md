# Downloads & external sources

**Namespace:** `census.Operations` ·
**FFL:** `src/census_us/handlers/downloads/ffl/census_operations.ffl` (+ the `census.types` schemas) ·
**Handlers:** `src/census_us/handlers/downloads/download_handlers.py` ·
**Impl:** `src/census_us/tools/_lib/downloader.py`, `src/census_us/tools/_lib/indicators.py` ·
**CLI:** `src/census_us/tools/download.sh`

## Overview

The ingest tier — the *source adapter* for everything downstream. It fetches raw
data from the Census Bureau (ACS demographics via the REST API, TIGER/Line
boundary shapefiles) plus a long tail of **external county/state indicator
series** (County Health Rankings, CDC, NCI, HUD, Pew, Zillow, election returns),
and normalizes each into a cached `CensusFile` (ACS-style CSV or a wide `y####`
time CSV) that the extract/render tiers consume without knowing the origin. Every
download is cache-first, so re-running a workflow re-fetches nothing.

## How it works

Two families, both returning the `census.types.CensusFile` schema
(`url, path, date, size, wasInCache`):

1. **Census-native downloads** (`downloader.py`):
   - `download_acs()` builds a `https://api.census.gov/data/<year>/acs/acs5?get=NAME,<cols>&for=…`
     request, parses the returned `[[header],[row]…]` JSON, and writes a CSV with a
     synthesized `GEOID` + `NAME` + the requested estimate columns. The `for`/`in`
     clause switches on geography: `&for=county:*&in=state:<fips>` (one state),
     `&for=county:*` (national, `state_fips="us"`), or `&for=state:*` (all states).
     County rows key on `0500000US<st><cty>`, state rows on `0400000US<st>`.
   - `download_tiger()` fetches `tl_<year>_<us|fips>_<suffix>.zip` from
     `https://www2.census.gov/geo/tiger/TIGER<year>/…`. COUNTY and STATE use the
     **national** file (`_TIGER_NATIONAL_GEO`); TRACT/BG/PLACE are per-state.
2. **External indicator series** (`indicators.py`, `build_*_csv` functions): each
   fetches a public source and emits a normalized county (or state) CSV — either an
   *indicator* CSV (`GEOID,NAME,<value-col>`, e.g. `chr_homicide`) rendered as a
   snapshot map, or a *wide time* CSV (`GEOID,NAME,y2010,y2011,…`) rendered as a
   year-slider map. Parsers are separated from fetchers so tests can exercise them
   offline.

Both the CLI (`download.sh`) and the FFL `DownloadACS`/`DownloadTIGER` handlers call
the same `downloader.py`, reading/writing one shared cache.

## Fan-out

**Single-task per download — no fan-out here.** Downloads are the leaf inputs that
*feed* fan-outs. The national ACS/TIGER pulls are deliberately single-task: the
Census API serves every county in the country in one `for=county:*` call, so the
national map families (see [workflows](workflows.md)) download **once** (cache-shared)
and fan out only over *metrics*, not geography. Per-path `threading.Lock`s
(`_get_lock`) collapse concurrent duplicate downloads within a runner.

## Data & fields

- **Default ACS batch** (`download_acs` default `columns`): a fixed ~44-column list —
  B01003 (pop), B19013 (income), B01002 (median age), B25064 (rent), B25001
  (housing), the B15003 bachelor's cells, B08301 (commuting), B25003 (tenure),
  B11001 (households), B25044 (vehicles), and — added later — B17001 (poverty) +
  B23025_003E/005E (labor force / unemployed). Kept under the API's 50-variable cap.
- **Extra batches** are separate requests because the default is near the cap:
  `DownloadACSDetailed` (B01001 sex-by-age, 49 cols), `DownloadACSSocial`
  (`_SOCIAL_TABLES` = B15003 full ladder + B19083 Gini + B19058 SNAP + B27001
  insurance), `DownloadACSDemographics` (`_DEMOGRAPHIC_TABLES` = B03002 race/eth +
  B05002 nativity + B07003 mobility).
- **External series** (facet → source): `DownloadCHR` (County Health Rankings —
  homicide + violent crime indicators, and BLS jobless 2002–2022 wide CSV),
  `DownloadCHRSeries` (one CHR measure across every release: obesity/life
  expectancy/smoking/diabetes), `DownloadHeartDiseaseTS` (CDC, 1999–2019),
  `DownloadCancerMortality` (NCI State Cancer Profiles snapshot), `DownloadDrugOverdoseTS`
  (NCHS 2003–2021), `DownloadSuicideTS` (CDC 2019–2024), `DownloadUnauthorizedTS`
  (Pew, by STATE, 1990–2023), `DownloadHomeValueTS` (Zillow ZHVI), `DownloadElectionTS`
  (county presidential margins 2008–2024), `DownloadHomelessTS` (HUD PIT apportioned
  to counties — takes a national ACS `acs_file` as the population weight/denominator).

## External libraries / binaries

- **`requests`** (pip, core dep) — all HTTP fetches (`HAS_REQUESTS` guard;
  `download_acs`/`download_tiger` raise `RuntimeError` if absent).
- **`openpyxl`** (pip) — read `.xlsx` sources in `indicators.py`.
- No shapefile libs here (TIGER is downloaded as a ZIP and parsed by the
  [tiger-geometry](tiger-geometry.md) tier).
- **`CENSUS_API_KEY`** (env secret) — required for the ACS5 API (see gotchas).

## Facets & workflows

All event facets, all `with Effect(kind = "external")`, `with Cost(tier = "moderate")`,
and a `with Timeout(minutes = 10–20)`:

| Facet | Purpose |
|---|---|
| `DownloadACS(year="2023", period="5-Year", state_fips)` | ACS summary file for a state (or `"us"` national) |
| `DownloadTIGER(year="2024", geo_level="COUNTY", state_fips)` | TIGER/Line shapefile ZIP |
| `DownloadACSDetailed(state_fips)` | B01001 sex-by-age batch (separate request) |
| `DownloadACSSocial(state_fips)` | education ladder + Gini + SNAP + insurance batch |
| `DownloadACSDemographics(state_fips)` | race/eth + nativity + mobility batch |
| `DownloadCHR()` → `(indicators_file, jobless_ts_file)` | County Health Rankings homicide/crime + jobless trends |
| `DownloadCHRSeries(measure)` | one CHR measure across all annual releases → wide CSV |
| `DownloadHeartDiseaseTS(topic, age)` | CDC heart/stroke mortality trends 1999–2019 |
| `DownloadCancerMortality()` | NCI county cancer-death snapshot |
| `DownloadDrugOverdoseTS()` / `DownloadSuicideTS()` | NCHS/CDC annual mortality wide CSVs |
| `DownloadUnauthorizedTS()` | Pew unauthorized-population by STATE |
| `DownloadHomeValueTS()` / `DownloadElectionTS()` | Zillow ZHVI / presidential margins wide CSVs |
| `DownloadHomelessTS(acs_file)` | HUD PIT apportioned to counties |

The `census.types` schemas (`CensusFile`, `ACSResult`, `TIGERResult`, `CensusSummary`)
are declared at the top of `census_operations.ffl`.

## Cache / output

Writes under `cstore.cache_root()` → `$FW_DATA_ROOT/cache/census-us/cache/` (s3://
on the fleet, `census-cache/` local). Layout: `acs/<year>/acs_<year>_<state>_<tag>.csv`,
`tiger/<year>/tl_<year>_<us|fips>_<suffix>.zip`, and the indicator/time CSVs under
their own subdirs. ACS cache is **column-validated** on hit — if the cached CSV is
missing any requested column it's treated as stale and re-fetched.

## Gotchas & notes

- **`CENSUS_API_KEY` is required.** The ACS5 API returns an **empty body** (→ JSON
  parse error) for these multi-column requests without a key. `download_acs` appends
  `&key=<…>` to the **request** URL only, never to the returned/cached `url`, so the
  secret never leaks into the step payload, Mongo, or the dashboard. Get a free key
  at `api.census.gov/data/key_signup.html`.
- **50-variable request cap.** Why age/social/demographics ride separate batches. If
  you add columns to the default pull, keep it under the cap or the whole request
  fails.
- **Empty extract ⇒ missing column.** If a downstream `Extract*` comes back empty,
  its table's columns are probably not in the default `columns` list (poverty +
  employment were missing until added; add the columns, not a new facet).
- **External series are as-published, with caveats.** Many are model-smoothed,
  suppressed for small counties, apportioned (HUD homeless), or estimate-only (Pew) —
  each workflow carries a `source_note` that the map surfaces verbatim; preserve it.
- `indicators.py` guards against **bot-challenge pages** ("suspiciously small
  download") so a captcha HTML body isn't silently parsed as data.

## Related specs

- [acs-extraction](acs-extraction.md) — consumes the ACS CSV.
- [tiger-geometry](tiger-geometry.md) — consumes the TIGER ZIP.
- [choropleth-maps](choropleth-maps.md) — consumes the indicator / wide-time CSVs.
- [storage-and-cache](storage-and-cache.md) — the backend-aware cache the downloads write to.
- [workflows](workflows.md) — the orchestration that wires downloads into pipelines.

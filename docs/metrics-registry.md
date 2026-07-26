# Metric registry (cross-cutting)

**Impl:** `src/census_us/tools/_lib/metrics.py` ·
**Consumed by:** `_lib/svi.py`, `_lib/maps.py`, `handlers/vulnerability/svi_handlers.py`

## Overview

The single source of truth for *what an indicator is and how to compute it*. Every
derived value in the domain — the SVI indicators, the per-state dropdown metrics, the
national rankings, and every national choropleth — is defined once as a `Metric` in
this registry and computed by one function. Adding a metric here makes it available to
every renderer without touching a renderer. This is a **cross-cutting** capability,
not a namespace of its own (there is no `census.Metrics` FFL surface).

## How it works

Each `Metric` (a dataclass) declares:

- `key` / `label` — the machine key and the human label (dropdown/ranking text).
- `fmt` — display format (`pct`, `dollar`, `index`, `count`, `years`, `per100k`,
  `per10k`, `density`, `margin`).
- `worse` — which direction is "worse": `high` (more = more vulnerable) or `low`
  (income, life expectancy). Drives rank order and whether the color ramp is reversed
  (so darker always = worse).
- `in_svi` — contributes to the Social Vulnerability Index.
- `num`/`den`/`raw`/`invert`/`scale` — the computation: a summed-numerator over
  denominator ratio (`num/den*scale`), a direct value column (`raw`), or an inverted
  ratio (`scale − …`, e.g. "no bachelor's" from the bachelor's-plus cells).
- `national_only` — the source columns exist only in the normalized national
  indicator/time CSVs (CHR/CDC/HUD/Zillow/election), never in the per-state joined
  GeoJSON, so the metric is kept off the state-map dropdowns.

`compute_metric(props, m)` resolves one metric for one feature's properties, returning
`None` when the source columns are missing or (for `raw`) hit the ACS large-negative
"no data" sentinel (`≤ −1e8`). `compute_metrics(props)` computes all of them.
`SVI_METRICS = [m for m in METRICS if m.in_svi]`; `BY_KEY` indexes by key;
`REQUIRED_TABLES` lists the ACS tables the full set needs joined.

## Data & fields

Representative registry entries (see `metrics.py` for the full ~40):

- **SVI / ratio metrics** (`in_svi=True`, `worse=high`): `poverty` (B17001),
  `unemployment` (B23025), `no_bachelors` (B15003, `invert`), `no_vehicle` (B25044),
  `elderly` (B01001 65+ bands), `renter` (B25003), `less_than_hs`, `hs_only`, `snap`
  (B19058), `uninsured` (B27001 no-coverage cells), `gini` (B19083, `raw`).
- **Standalone ACS metrics** (`in_svi=False`): `grad_degree` (`worse=low`),
  `median_income` (B19013, `raw`, `worse=low`), `total_population` (B01001_001E),
  `median_age` (B01002_001E), `median_rent` (B25064_001E), plus race/ethnicity /
  nativity / mobility (`people_of_color`, `hispanic`, `black`, `asian`, `white_nh`,
  `foreign_born`, `recent_movers` — B03002/B05002/B07003).
- **`national_only` external-source metrics** (a `raw` column injected by the
  indicator/time-CSV builders): `homicide`/`violent_crime` (`chr_*`), `homeless_rate`
  (`hud_*`), `obesity`/`life_expectancy`/`smoking`/`diabetes` (`chr_*`),
  `heart_disease`/`drug_overdose`/`suicide` (`cdc_*`), `cancer_mortality` (`scp_*`),
  `unauthorized_population` (`pew_*`), `home_value` (`zhvi_*`), `party_margin`
  (`elec_margin`), `population_density` (B01003_001E, per-sq-mi).

## Fan-out

Not applicable — a pure in-process library, no tasks. (Says so rather than dropping
the heading.)

## External libraries / binaries

None — stdlib + dataclasses only.

## Facets & workflows

None — this registry has **no FFL surface**. It is invoked from the render/SVI
handlers, not addressed by name. The FFL-visible metric knob is the `metric: String`
parameter on the `BuildNational*` / `BuildCounty*` facets and workflows, whose value
must be a registry `key`.

## Cache / output

None of its own — it computes values the renderers write into their GeoJSON/HTML.

## Gotchas & notes

- **`metric` params must be registry keys.** A workflow passing `metric="income"`
  (instead of `median_income`) raises `Unknown metric: … Known: [...]` in
  `build_national_county_map`. The default `maps` lists in the workflows use valid keys.
- **`worse` drives color + rank, not just sorting.** Getting it wrong flips the map
  (dark = good). Income and life-expectancy are the `worse=low` cases.
- **Adding a metric is registry-only** for ACS-column metrics; a `national_only`
  metric additionally needs its `raw` column produced by an indicator/time-CSV builder
  in [downloads](downloads.md).
- **`REQUIRED_TABLES` is the join contract** — the per-state metrics path must join
  every table in it or those metrics come back `None`.

## Related specs

- [choropleth-maps](choropleth-maps.md) — the renderers that read the registry.
- [svi](svi.md) — the `in_svi` subset.
- [summary-and-join](summary-and-join.md) — joins the `REQUIRED_TABLES` columns onto geometry.
- [downloads](downloads.md) — produces the `national_only` source columns.

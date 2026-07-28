# FFL Examples — `census-us`

Every numbered scenario is a **complete, compilable FFL file**. Copy one into
`my.ffl` and run it:

```bash
fw ffl run --primary my.ffl \
  --library ~/fw_handlers/fwh_census_us/src/census_us/ffl/census.ffl \
  --workflow my.census.<WorkflowName>
```

A runner serving the `census` namespace must be up
(`fw runner start --domain census-us`), with `CENSUS_API_KEY` in its environment
for the ACS pulls. Every block below is compile-checked against
`src/census_us/ffl/census.ffl`.

New to the language? Start with the
[FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md)
and the [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical).

---

## The building blocks

Download-once facets, a family of ~15 `Extract*` facets that all take the same
`CensusFile` and return the same `ACSResult`, and join/summarise/render/publish
stages on top. The uniform shape is what makes an extract easy to add or swap.

| Declaration | Role |
|---|---|
| `census.Operations.DownloadACS(year, period, state_fips) => (file: CensusFile)` | ACS pull (also `DownloadACSDetailed`, `…Social`, `…Demographics`) |
| `census.Operations.DownloadTIGER(year, geo_level, state_fips) => (file)` | Geometry pull |
| `census.ACS.Extract*(file, state_fips, geo_level) => (result: ACSResult)` | Population, income, housing, education, commuting, tenure, households, age, vehicles, race, poverty, employment, gini, snap, insurance |
| `census.Publish.PublishWebBundle(repo, prefixes, dests, labels, …)` | The **generic publisher every map domain reuses** |
| `census.workflows.AnalyzeState` / `BuildIncomeMapUS` / `BuildCountyMapsUS` / `BuildRankings` / `PublishToSite` / … | ~24 shipped entry points |

Results are **schemas**, so fields nest: `pop.result.output_path`.

---

## 1. Run what ships — no FFL to write

```bash
fw ffl seed --include census-us

fw ffl run --workflow census.workflows.AnalyzeState \
  --inputs '{"state_fips": "41", "state_name": "Oregon"}'

fw ffl run --workflow census.workflows.BuildIncomeMapUS \
  --inputs '{"year": "2023"}'
```

Write FFL when you want a different *shape* — your own subset of extracts, a
state fan-out, extra error handling, or a publish step chained onto a build.

## 2. The smallest workflow you can write

Every FFL workflow needs a `namespace`, a `use` per namespace it calls into, and a
`yield` back to itself.

```ffl
namespace my.census {

    use census.Operations
    use census.ACS

    /** Download one state's ACS, extract income. */
    workflow StateIncome(state_fips: String = "41") => (path: String, rows: Long) andThen {

        acs = census.Operations.DownloadACS(state_fips = $.state_fips)

        income = census.ACS.ExtractIncome(file = acs.file, state_fips = $.state_fips)

        yield StateIncome(path = income.result.output_path, rows = income.result.record_count)
    }
}
```

Rules visible above: `=>` sits on the **same line** as the closing `)`; references
are always `step.field` and schema results nest one level
(`income.result.output_path`); `$.state_fips` reads the workflow's parameter.

## 3. One download, many extracts — parallelism for free

Every `Extract*` references only the download, never each other, so the runtime
dispatches them **concurrently**. This is the shape of the shipped `AnalyzeState`.

```ffl
namespace my.census {

    use census.Operations
    use census.ACS

    /** One ACS pull, five extracts in parallel. */
    workflow StateProfile(state_fips: String = "41") => (income: String, poverty: String) andThen {

        acs = census.Operations.DownloadACS(state_fips = $.state_fips)

        pop = census.ACS.ExtractPopulation(file = acs.file, state_fips = $.state_fips)
        income = census.ACS.ExtractIncome(file = acs.file, state_fips = $.state_fips)
        housing = census.ACS.ExtractHousing(file = acs.file, state_fips = $.state_fips)
        poverty = census.ACS.ExtractPoverty(file = acs.file, state_fips = $.state_fips)
        employment = census.ACS.ExtractEmployment(file = acs.file, state_fips = $.state_fips)

        yield StateProfile(
            income = income.result.output_path,
            poverty = poverty.result.output_path)
    }
}
```

Adding a sixth extract is one more line — it joins the parallel batch
automatically.

## 4. Array arguments — feeding many paths into one step

`JoinGeo` takes a list of extract outputs. Array literals are ordinary
expressions, so the fan-in is written inline.

```ffl
namespace my.census {

    use census.Operations
    use census.ACS
    use census.TIGER
    use census.Summary

    /** Extract three datasets, then join them onto county geometry. */
    workflow JoinThree(state_fips: String = "41") => (joined: String) andThen {

        acs = census.Operations.DownloadACS(state_fips = $.state_fips)
        tiger = census.Operations.DownloadTIGER(state_fips = $.state_fips, geo_level = "COUNTY")

        pop = census.ACS.ExtractPopulation(file = acs.file, state_fips = $.state_fips)
        income = census.ACS.ExtractIncome(file = acs.file, state_fips = $.state_fips)
        poverty = census.ACS.ExtractPoverty(file = acs.file, state_fips = $.state_fips)

        counties = census.TIGER.ExtractCounties(file = tiger.file, state_fips = $.state_fips)

        joined = census.Summary.JoinGeo(
            acs_path = pop.result.output_path,
            tiger_path = counties.result.output_path,
            extra_acs_paths = [income.result.output_path, poverty.result.output_path])

        yield JoinThree(joined = joined.result.output_path)
    }
}
```

## 5. Fan out over states — `foreach`

`andThen foreach v in <list>` runs the body once per state, each as its own set of
runtime steps that the fleet claims in parallel. Here the `foreach` hangs off the
**workflow**, so the loop variable and the workflow's parameters share one `$`.

```ffl
namespace my.census {

    use census.Operations
    use census.ACS

    /** One income extract per state, all states in parallel. */
    workflow IncomeByState(states: Json) => (paths: [String]) andThen foreach st in $.states {

        acs = census.Operations.DownloadACS(state_fips = $.st)

        income = census.ACS.ExtractIncome(file = acs.file, state_fips = $.st)

        yield IncomeByState(paths = [income.result.output_path])
    }
}
```

```bash
fw ffl run --primary my.ffl --library …/census.ffl --workflow my.census.IncomeByState \
  --inputs '{"states": ["41", "06", "48", "36"]}'
```

> ⚠️ 51-state fan-outs of the heavy builds have filled a Docker VM's disk before.
> Serialize or disk-guard large fan-outs — see the
> [disk-guard command](https://github.com/rlemke/facetwork/blob/main/docs/operations/fleet-rollouts.md).

## 6. Publish — the facet the whole fleet reuses

`census.Publish.PublishWebBundle` pushes any set of storage prefixes to a GitHub
Pages site in one commit. Other domains `use census.Publish` for exactly this.

```ffl
namespace my.census {

    use census.Publish

    /** Push two output bundles in a single commit. */
    workflow PublishTwo(repo: String = "rlemke/facetwork-maps") => (pages_url: String, files: Long) andThen {

        published = census.Publish.PublishWebBundle(
            repo = $.repo,
            prefixes = ["census/output/income", "census/output/svi"],
            dests = ["us/income", "us/svi"],
            labels = ["Median household income", "Social vulnerability index"],
            landing_title = "Facetwork maps")

        yield PublishTwo(pages_url = published.pages_url, files = published.file_count)
    }
}
```

## 7. Branch on a result — `when`

A `when` block hangs off the step it inspects: inside a case `$` is that step and
`$$` reaches the workflow. Every `when` needs a default case, last, and conditions
must be real `Boolean`s (no truthy coercion).

```ffl
namespace my.census {

    use census.Operations
    use census.ACS

    /** Don't extract from a suspiciously small download. */
    workflow GuardedExtract(state_fips: String = "41", min_bytes: Long = 1000) => (status: String, path: String) andThen {

        acs = census.Operations.DownloadACS(state_fips = $.state_fips) andThen when {
            case $.file.size_bytes >= $$.min_bytes => {
                income = census.ACS.ExtractIncome(file = $.file, state_fips = $$.state_fips)
                yield GuardedExtract(status = "extracted", path = income.result.output_path)
            }
            case _ => {
                yield GuardedExtract(status = "download_too_small", path = "")
            }
        }
    }
}
```

## 8. Call-time mixins and `catch`

The Census API is the flaky part; override the timeout/retry for one call and
degrade instead of failing.

```ffl
namespace my.census {

    use census.Operations
    use census.ACS

    /** Patient download, clean failure. */
    workflow ResilientExtract(state_fips: String = "41") => (status: String, path: String) andThen {

        acs = census.Operations.DownloadACS(
            state_fips = $.state_fips) with Timeout(minutes = 30) with Retry(maxAttempts = 3, backoffSeconds = 60) catch {
            yield ResilientExtract(status = "census_api_unavailable", path = "")
        }

        income = census.ACS.ExtractIncome(file = acs.file, state_fips = $.state_fips)

        yield ResilientExtract(status = "extracted", path = income.result.output_path)
    }
}
```

## 9. Reuse the shipped workflows

```ffl
namespace my.census {

    use census.workflows

    /** Build the national income map, then publish it. */
    workflow BuildThenPublish(year: String = "2023") => (headline: String, pages_url: String) andThen {

        built = census.workflows.BuildIncomeMapUS(year = $.year)

        published = census.workflows.PublishToSite(
            prefixes = ["census/output/income"],
            dests = ["us/income"],
            labels = ["Median household income"])

        yield BuildThenPublish(
            headline = "income map: " ++ built.status,
            pages_url = published.pages_url)
    }
}
```

> The publish step doesn't reference the build, so the two are independent — run
> them as separate submissions, or gate the publish with a `when` on
> `built.status`, if you need the order guaranteed.

---

## Cheat sheet

| You want to… | Write |
|---|---|
| Read a workflow/step parameter | `$.name` (`$$.name` one level out) |
| Read a previous step's result | `stepname.field` — schema results nest: `income.result.output_path` |
| Run steps in parallel | write them with no reference between them |
| Pass many results into one step | an array literal: `extra_acs_paths = [a.result.output_path, b.result.output_path]` |
| Fan out over a list | `workflow W(items: Json) … andThen foreach i in $.items { … }` |
| More time / retries for one call | `… with Timeout(minutes = 30) with Retry(maxAttempts = 3, backoffSeconds = 60)` |
| Handle a step failure | `step = Facet(…) catch { yield … }` |
| Branch | `step = Facet(…) andThen when { case <bool> => { … } case _ => { … } }` |
| Concatenate strings | `a ++ b` |

**Validate before you run:** `afl my.ffl --check` or MCP `fw_validate`. Every error
carries a `rule_id` — fetch `fw://docs/rules/{rule_id}` for a wrong/right pair.

## See also

- [`docs/README.md`](README.md) — per-feature specs for this domain
- [FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md) ·
  [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical) ·
  [relative `$`-scoping](https://github.com/rlemke/facetwork/blob/main/docs/architecture/ffl-relative-scoping.md)
- `src/census_us/ffl/census.ffl` — the source of truth for every signature above

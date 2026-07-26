# ACS variable vocabulary (NL → table)

**Namespace:** `census.Vocab` ·
**FFL:** `src/census_us/handlers/vocab/ffl/census_vocab.ffl` ·
**Handlers:** `src/census_us/handlers/vocab/vocab_handlers.py` ·
**Impl:** `src/census_us/tools/_lib/acs_extractor.py` (`ACS_TABLES`) ·
**Tests:** `src/census_us/handlers/vocab/tests/test_vocab_handlers.py`

## Overview

The semantic discovery half of the domain: resolve a natural-language indicator
("median income", "poverty rate", "total population") to the ACS **table ID +
estimate column codes** it denotes, so an LLM composer turns "median income by
county" into `B19013 → census.ACS.ExtractIncome` without memorising the Census
variable catalogue. It is the domain-ontology counterpart to the platform's
facet-capability index (`fw_capabilities`) — one answers *what facet*, this answers
*what variable*.

## How it works

Pure in-process lookups over the static `ACS_TABLES` catalogue (no network, no
cache):

- `ResolveVariable(term)` tokenizes the term (`[a-z0-9]+`) and scores it against
  each table's canonical label **plus** a hand-curated `_SYNONYMS` phrase list
  (e.g. B19013 ← "income", "median household income", "earnings"). `_score` is a
  Jaccard-ish token overlap with an exact-phrase bonus (1.0 on an exact match,
  capped at 0.95 otherwise). Returns the best `{table_id, label, columns,
  confidence, matched_term, alternatives}`; `confidence 0` + empty `table_id`
  means "not in the vocabulary".
- `ListVariables()` returns every covered table as `{table_id, label, columns}`.

`Json`-typed returns (`columns`, `alternatives`, `variables`) are emitted as JSON
**strings**, matching the fleet convention (e.g. `osm.Vocab`).

## Fan-out

**Single-task — no fan-out.** Pure, sub-millisecond dictionary lookups; nothing to
distribute.

## Data & fields

- **Source of truth:** `ACS_TABLES` in `acs_extractor.py` (shared with the
  extraction tier — the vocabulary and the extractor can't drift because they read
  the same catalogue).
- **Synonyms:** `_SYNONYMS` in `vocab_handlers.py` covers the 12 core tables
  (B01003, B19013, B25001, B15003, B08301, B25003, B11001, B01001, B25044, B02001,
  B17001, B23025); the Gini/SNAP/insurance/demographic tables resolve via their
  `ACS_TABLES` labels.
- **Output schema:** `ACSVariable` (`table_id, label, columns: Json, confidence:
  Double, matched_term, alternatives: Json`).

## External libraries / binaries

None — stdlib `json`/`re` only. This is the one namespace with no I/O.

## Facets & workflows

Both event facets, both `with Effect(kind = "pure")` / `with Cost(tier = "free")`
(the only pure/free facets in the domain):

| Facet | Purpose |
|---|---|
| `ResolveVariable(term: String) => (result: ACSVariable)` | NL indicator → best ACS table + columns + ranked alternatives |
| `ListVariables() => (variables: Json, count: Long)` | enumerate every covered ACS table |

Declared `event facet` in FFL, so they run through a handler even though the work
is pure; they carry the `pure`/`free` mixins so a composer prefers them freely.

## Cache / output

None — no files written. Results flow back in the step payload only.

## Gotchas & notes

- **Resolution is lexical, not learned.** It matches tokens against labels +
  synonyms; an indicator phrased entirely outside the synonym set returns
  low/zero confidence. Extend `_SYNONYMS` (additive — no behaviour change to
  extraction) rather than reaching for a fuzzier matcher.
- **Feed `table_id` straight into the matching `census.ACS.Extract*`** — the
  vocabulary is the deterministic NL→variable step *before* extraction, not a
  data source itself.

## Related specs

- [acs-extraction](acs-extraction.md) — consumes the resolved `table_id`.
- [downloads](downloads.md) — the tables must be in the download batch to be extractable.
- [metrics-registry](metrics-registry.md) — the derived-metric analogue (raw columns → named metric).

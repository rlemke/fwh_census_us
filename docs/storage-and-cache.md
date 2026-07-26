# Storage & cache (cross-cutting)

**Impl:** `src/census_us/tools/_lib/storage.py` (imported as `cstore` everywhere) ·
**Consumed by:** every `_lib` module and, through the shim, every handler ·
**Spec:** `agent-spec/cache-layout.agent-spec.yaml`

## Overview

The backend-aware I/O layer that lets one code path run identically on a laptop
(local disk) and on the fleet (shared MinIO/S3). Every download, extract, join,
summary, SVI, and map artifact is read and written through this thin wrapper over
`facetwork.runtime.storage`, so on the fleet everything lands in the shared object
store (any runner on any host resolves the same `s3://` URIs) instead of siloing to a
runner's local disk. It is a **cross-cutting** capability, not an FFL namespace.

## How it works

`storage.py` resolves two roots and provides object-store-safe I/O:

- **`cache_root()` / `output_root()`** — resolve under `FW_DATA_ROOT` (an `s3://` URI
  on the fleet) → `s3://…/cache/census-us/cache` and `…/output`; fall back to local
  `census-cache/` / `census-output/` under the output base when `FW_DATA_ROOT` isn't
  remote. The `FW_CENSUS_CACHE_DIR` / `FW_CENSUS_OUTPUT_DIR` env overrides always win
  (explicit local placement).
- **`join(*parts)`** — a POSIX-style join that is safe for `s3://` URIs (`os.path.join`
  mangles them). **Always build census paths with `cstore.join`.**
- **`open_write(path)`** — local: `makedirs` + plain `open`. Remote: stage to a local
  temp file (so the caller's `newline=`/encoding and the `csv`/`json` writers behave
  exactly as on local disk), then push the finished bytes to the object store on close
  — object stores don't do partial writes, so a half-written object never appears.
- **`open_read` / `localize(path)`** — pull a remote URI down to a real local file
  before any reader that needs a path (`csv`, `zipfile`, `fiona`, `pyshp`) touches it.
- **`exists` / `size`** — dispatch to the right backend for a path.

Local backend is a pure pass-through, so terminal CLI use and offline tests are
unaffected.

## Fan-out

Not applicable — a library. (Kept as a heading rather than dropped.) It is *what makes*
fleet fan-out correct, though: portable `s3://` payloads mean a fan-out task can run on
any host without shared disk.

## Data & fields

- **Roots:** `FW_DATA_ROOT` (fleet `s3://afl-cache`), overrides `FW_CENSUS_CACHE_DIR`
  / `FW_CENSUS_OUTPUT_DIR`.
- **Cache layout** (under `cache_root()`): `acs/<year>/…`, `tiger/<year>/…`, and the
  indicator/time CSVs. **Output layout** (under `output_root()`): `acs/`, `tiger/`,
  `joined/`, `summary/`, `national/`, `metrics/`, `svi/`, `rankings/`.

## External libraries / binaries

- **`facetwork.runtime.storage`** — the underlying multi-backend (local / `s3://` /
  `hdfs://`) implementation; this module is a census-flavored convenience wrapper.
- No third-party deps of its own.

## Facets & workflows

None — no FFL surface. Invoked as `cstore.*` from the `_lib` modules.

## Cache / output

It *is* the cache/output layer. On the fleet: `s3://afl-cache/cache/census-us/…`; the
console is MinIO at `:9001` (`minioadmin`/`minioadmin`). Locally: `census-cache/` /
`census-output/` under `FW_DATA_ROOT`.

## Gotchas & notes

- **Never `os.path.join` an `s3://` path** — use `cstore.join`, or the URI is mangled.
- **Never hand a remote URI to a file reader** — `localize()` first (fiona/pyshp/
  zipfile/csv need a real local file). The TIGER and join readers already do this.
- **Stage-then-finalize on writes** is why partial objects never appear on the fleet;
  keep any local scratch (`FW_OUTPUT_BASE` / `FW_LOCAL_SCRATCH`) local.
- **`FW_CENSUS_CACHE_DIR` / `FW_CENSUS_OUTPUT_DIR` override everything** — handy to pin
  a local dir on a fleet host for debugging, but they take precedence over
  `FW_DATA_ROOT`.

## Related specs

- [downloads](downloads.md) — writes the cache through this wrapper.
- [tiger-geometry](tiger-geometry.md) / [summary-and-join](summary-and-join.md) — localize-before-read.
- [publish](publish.md) — walks + localizes the output prefixes.

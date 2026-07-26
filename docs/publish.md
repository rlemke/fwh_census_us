# Publish to GitHub Pages

**Namespace:** `census.Publish` ·
**FFL:** `src/census_us/handlers/publish/ffl/census_publish.ffl` ·
**Handlers:** `src/census_us/handlers/publish/publish_handlers.py` ·
**Impl:** `src/census_us/tools/_lib/publish.py` ·
**Tests:** `tests/test_publish_merge.py`

## Overview

The last-mile publisher: take a set of rendered output bundles (storage prefixes in
MinIO / local paths) and push them to a **GitHub Pages** repo in one commit, so the
maps are served at `https://<owner>.github.io/<name>/<dest>/…`. It is a generic
"git web repo publish" primitive — the census stats site is the default target, but
any prefixes (e.g. save-earth world maps) can ride the same token-gated publisher.

## How it works

`publish_bundles(repo, prefixes, dests, …)` (publish.py):

1. Resolve each `prefix` (a bare name → the census `output_root()`; a full path /
   `s3://` URI → used as-is).
2. Shallow-clone the repo over HTTPS with an injected token, then for each bundle
   walk the storage backend, `localize()` every object to a real local file, and copy
   it into the clone under `dest` — **preserving the relative layout** so each map's
   relative `./<state>/index.html` + companion GeoJSON links keep working. Only the
   `dest` subtree is replaced, leaving other bundles in the same repo untouched.
3. Write a small landing `index.html` linking the bundles, then `git commit` +
   `git push`. Returns `PublishResult` (`repo, branch, file_count, bytes_published,
   commit, pages_url`).

## Fan-out

**Single-task, and pinned to one host.** Publishing is one clone+commit+push; it must
land on the host that holds the GitHub credential. See the routing note below.

## Data & fields

- **Inputs:** `prefixes` (parallel to `dests`), optional `labels` (landing link
  text), `include` (a file-suffix allowlist, e.g. `[".html"]`), `descriptions` (a JSON
  object of per-section blurbs). `PublishStatsSite` publishes the standard three
  bundles (`metrics`, `rankings`, `svi` → `census/metrics`, `census/rankings`,
  `census/svi`); `PublishToSite` is the generic arbitrary-prefix variant.
- **Output schema:** `pages_url, file_count, bytes_published, commit`.

## External libraries / binaries

- **`git`** — a **binary** dependency (`subprocess` clone/commit/push).
- **stdlib `urllib`** for the token-authenticated remote; `facetwork.runtime.storage`
  + the `_lib.storage` wrapper to localize MinIO objects.
- **`GITHUB_TOKEN`** (or `GH_TOKEN`) — an env secret; the remote is
  `https://x-access-token:<token>@github.com/<owner>/<name>.git`. Never echoed (the
  `_run` error message is argument-free; git redacts its own).

## Facets & workflows

| Facet / workflow | Effect/Cost | Purpose |
|---|---|---|
| `census.Publish.PublishWebBundle(repo, prefixes, dests, …)` | external / expensive / 30m | the primitive: localize prefixes → commit → push |
| `census.workflows.PublishStatsSite(repo, branch, include)` | — | publish the three standard census bundles |
| `census.workflows.PublishToSite(repo, prefixes, dests, labels, …)` | — | generic arbitrary-prefix publish (non-census outputs too) |

`PublishWebBundle` is an event facet; the two workflows wrap it and expose a clickable
`pages_url` result.

## Cache / output

Reads output bundles from `output_root()` (MinIO on the fleet); writes to the target
**GitHub repo / Pages site** (not the file cache or Mongo). The `pages_url` result
renders an "Open map" link in the dashboard.

## Gotchas & notes

- **Token gate + execution gate — the double lock that lands it on the right host.**
  `register_handlers` only registers `PublishWebBundle` where a token exists, so a
  `--registry` runner without one never advertises (and never claims) the facet. But
  task routing is by the `census` namespace, so a credential-less census runner
  *could* still claim it — the `handle()` entrypoint therefore re-checks the token and
  raises **`ModuleNotFoundError`** on a token-less host, the one exception the runtime
  treats as "release back to pending" (not a failure), so the credentialed host picks
  it up. (Grounded in `publish_handlers.py`.)
- **Object stores have no directory tree** — every object is walked + localized before
  the copy; the clone is shallow and only the `dest` subtree is replaced.
- **`git` must be on PATH** on the publishing host.

## Related specs

- [choropleth-maps](choropleth-maps.md) / [svi](svi.md) — produce the bundles this publishes.
- [storage-and-cache](storage-and-cache.md) — the MinIO prefixes + localize contract.
- [workflows](workflows.md) — `PublishStatsSite` / `PublishToSite`.

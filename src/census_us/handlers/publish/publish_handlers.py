"""Event facet handler for census.Publish.PublishWebBundle.

Publishes output bundles (MinIO prefixes) to a GitHub Pages repo. A thin
coercion layer over ``_lib.publish.publish_bundles``.

Execution is pinned to credentialed hosts: the facet is registered ONLY when a
``GITHUB_TOKEN`` (or ``GH_TOKEN``) is present in the runner's environment. A
``--registry`` runner advertises (and so claims) a facet only if its handler is
registered, and ``claim_task`` is name-filtered server-side — so a runner with
no token never claims a publish task, and it lands on the one host that can push.
"""

import os
from typing import Any

from ..shared.census_utils import publish_bundles

NAMESPACE = "census.Publish"


def _has_token() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))


def handle_publish_web_bundle(params: dict[str, Any]) -> dict[str, Any]:
    """Publish one or more storage prefixes to a GitHub Pages repo.

    Params:
        repo: "owner/name" of the target GitHub repo.
        prefixes: storage prefixes to publish (bare name → census output root,
            or a full local path / s3:// URI).
        dests: per-prefix path within the repo (same length as prefixes).
        branch: target branch (default "main").
        landing_title: title for the generated root index.html.
        include: optional file-suffix allowlist (e.g. [".html"] for HTML-only).
    """
    repo = params.get("repo", "") or ""
    prefixes = params.get("prefixes") or []
    dests = params.get("dests") or []
    branch = params.get("branch", "main") or "main"
    landing_title = params.get("landing_title", "Facetwork statistics") or "Facetwork statistics"
    include = params.get("include") or []
    labels = params.get("labels") or []
    # descriptions: a JSON object {section: text, "": root_text} (section = the
    # first dest path segment, e.g. "world"/"census"); empty key = root landing.
    descriptions = params.get("descriptions") or {}
    if isinstance(descriptions, str):
        import json as _json
        try:
            descriptions = _json.loads(descriptions) if descriptions.strip() else {}
        except ValueError:
            descriptions = {}
    step_log = params.get("_step_log")
    if not repo:
        raise ValueError("PublishWebBundle requires repo ('owner/name')")
    try:
        res = publish_bundles(
            repo, list(prefixes), list(dests),
            branch=branch, landing_title=landing_title, include=list(include),
            labels=list(labels), descriptions=dict(descriptions),
        )
        if step_log:
            step_log(
                f"PublishWebBundle: pushed {res.file_count} files "
                f"({res.bytes_published / 1e6:.1f} MB) to {res.repo}@{res.commit[:8]} "
                f"-> {res.pages_url}",
                level="success",
            )
        return {
            "pages_url": res.pages_url,
            "file_count": res.file_count,
            "bytes_published": res.bytes_published,
            "commit": res.commit,
        }
    except Exception as exc:
        if step_log:
            step_log(f"PublishWebBundle: {exc}", level="error")
        raise


_DISPATCH: dict[str, Any] = {
    f"{NAMESPACE}.PublishWebBundle": handle_publish_web_bundle,
}


def handle(payload: dict) -> dict:
    """RegistryRunner dispatch entrypoint."""
    facet_name = payload["_facet_name"]
    handler = _DISPATCH.get(facet_name)
    if handler is None:
        raise ValueError(f"Unknown facet: {facet_name}")
    return handler(payload)


def register_handlers(runner) -> None:
    """Register the publish facet with a RegistryRunner — only where a GitHub
    token exists, so the publish task is claimed on the credentialed host."""
    if not _has_token():
        return
    for facet_name in _DISPATCH:
        runner.register_handler(
            facet_name=facet_name,
            module_uri=f"file://{os.path.abspath(__file__)}",
            entrypoint="handle",
        )


def register_publish_handlers(poller) -> None:
    """Register publish handlers with an AgentPoller (token-gated)."""
    if not _has_token():
        return
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)

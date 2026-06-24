"""Publish output bundles (storage prefixes) to a GitHub Pages repo.

Generic "git web repo publish" primitive: given a GitHub repo and a set of
storage prefixes (local paths or ``s3://`` URIs in MinIO), localize every
object under each prefix, copy it into the repo under a matching ``dest`` path
(preserving the relative layout so the maps' relative ``./<state>/index.html`` +
``metrics.geojson`` links keep working), write a small landing ``index.html``
linking the bundles, then ``git commit`` + ``git push``. GitHub Pages then
serves the tree at ``https://<owner>.github.io/<name>/<dest>/...``.

Auth: a ``GITHUB_TOKEN`` (or ``GH_TOKEN``) in the environment — pushed over
HTTPS as ``https://x-access-token:<token>@github.com/<owner>/<name>.git``. The
handler only *registers* where that token exists, so the publish task is claimed
exactly on the host that holds credentials (server-side name filter).

Object stores have no concept of a directory tree as files on disk, so we walk
the backend, localize each object to a real local path, and copy it into the
working clone. The clone is shallow; only the ``dest`` subtree is replaced on a
re-publish, so other bundles in the same repo are left untouched.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from html import escape

from facetwork.runtime import storage as _fws

from . import storage as cstore


@dataclass
class PublishResult:
    repo: str
    branch: str
    file_count: int
    bytes_published: int
    commit: str
    pages_url: str


def _run(cmd: list[str], *, cwd: str | None = None, env: dict | None = None,
         check: bool = True) -> subprocess.CompletedProcess:
    res = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if check and res.returncode != 0:
        # Never echo the remote URL (it carries the token) — git already redacts
        # it in its own messages, but keep our own message argument-free.
        raise RuntimeError(
            f"`git {cmd[1] if cmd[0] == 'git' else cmd[0]}` failed "
            f"({res.returncode}): {(res.stderr or res.stdout).strip()[:500]}"
        )
    return res


def _resolve_prefix(prefix: str) -> str:
    """A bare name (e.g. ``metrics``) resolves under the census output root; a
    full URI / absolute path is used as-is (keeps the facet reusable)."""
    if "://" in prefix or prefix.startswith("/"):
        return prefix.rstrip("/")
    return cstore.join(cstore.output_root(), prefix).rstrip("/")


def _download_tree(prefix: str, dest_dir: str,
                   include: tuple[str, ...] = ()) -> tuple[int, int]:
    """Copy every object under ``prefix`` into ``dest_dir``, preserving the
    relative path. If ``include`` is non-empty, only files whose (lowercased)
    name ends with one of those suffixes are copied (e.g. ``(".html",)`` for an
    HTML-only publish — the census maps embed their GeoJSON inline, so the .html
    is self-contained and the separate .geojson sidecars can be skipped).
    Returns (file_count, total_bytes)."""
    backend = _fws.get_storage_backend(prefix)
    base = prefix.rstrip("/")
    n = 0
    total = 0
    for dirpath, _dirs, files in backend.walk(base):
        for fn in files:
            if include and not fn.lower().endswith(include):
                continue
            src = cstore.join(dirpath, fn)
            rel = src[len(base):].lstrip("/")
            out = os.path.join(dest_dir, rel)
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            shutil.copyfile(cstore.localize(src), out)
            n += 1
            total += os.path.getsize(out)
    return n, total


def _landing_html(title: str, links: list[tuple[str, str]]) -> str:
    items = "\n".join(
        f'    <li><a href="{escape(dest)}/index.html">{escape(label)}</a></li>'
        for label, dest in links
    )
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
        f"<title>{escape(title)}</title>\n"
        "<style>body{font-family:system-ui,sans-serif;max-width:40rem;margin:3rem auto;"
        "padding:0 1rem;line-height:1.6}h1{font-size:1.4rem}li{margin:.4rem 0}</style>\n"
        f"</head><body>\n<h1>{escape(title)}</h1>\n<ul>\n{items}\n</ul>\n"
        "<p style=\"color:#888;font-size:.85rem\">Published from Facetwork.</p>\n"
        "</body></html>\n"
    )


def _ensure_pages(repo: str, branch: str, token: str) -> None:
    """Best-effort enable of GitHub Pages (source = branch root). A failure here
    must not fail the publish — the push already succeeded."""
    api = f"https://api.github.com/repos/{repo}/pages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    }
    body = json.dumps({"source": {"branch": branch, "path": "/"}}).encode()
    req = urllib.request.Request(api, data=body, headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        # 409 = already enabled; 422 = already configured / validation — both fine.
        if e.code not in (409, 422):
            pass  # 404 etc. — Pages stays whatever it was; the files are pushed.
    except (urllib.error.URLError, TimeoutError):
        pass


def publish_bundles(
    repo: str,
    prefixes: list[str],
    dests: list[str],
    *,
    branch: str = "main",
    landing_title: str = "Facetwork statistics",
    include: list[str] | None = None,
    token: str | None = None,
) -> PublishResult:
    """Publish each ``prefixes[i]`` into ``repo`` at ``dests[i]``; push once.

    ``include`` restricts which files are published by suffix (e.g. ``[".html"]``
    for an HTML-only site); empty/None publishes every object under each prefix.
    Returns the public Pages URL of the landing page (or the first dest)."""
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN (or GH_TOKEN) is not set in the environment")
    if "/" not in repo:
        raise ValueError("repo must be 'owner/name'")
    if len(prefixes) != len(dests):
        raise ValueError("prefixes and dests must be the same length")
    if not prefixes:
        raise ValueError("at least one prefix is required")
    owner, name = repo.split("/", 1)
    inc = tuple(s.lower() for s in (include or []))

    work = tempfile.mkdtemp(prefix="ghpages_")
    repo_dir = os.path.join(work, "repo")
    url = f"https://x-access-token:{token}@github.com/{repo}.git"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        clone = _run(["git", "clone", "--depth", "1", "--branch", branch, url, repo_dir],
                     env=env, check=False)
        if clone.returncode != 0:
            # Fresh/empty repo (or branch missing) — init a new branch.
            os.makedirs(repo_dir, exist_ok=True)
            _run(["git", "init", "-q"], cwd=repo_dir, env=env)
            _run(["git", "checkout", "-q", "-b", branch], cwd=repo_dir, env=env)
            _run(["git", "remote", "add", "origin", url], cwd=repo_dir, env=env)
        _run(["git", "config", "user.email", "facetwork-publish@localhost"], cwd=repo_dir, env=env)
        _run(["git", "config", "user.name", "facetwork-publish"], cwd=repo_dir, env=env)

        total_n = 0
        total_b = 0
        links: list[tuple[str, str]] = []
        for prefix, dest in zip(prefixes, dests):
            resolved = _resolve_prefix(prefix)
            target = os.path.join(repo_dir, dest) if dest else repo_dir
            if os.path.isdir(target):
                shutil.rmtree(target)  # idempotent re-publish of just this subtree
            os.makedirs(target, exist_ok=True)
            n, b = _download_tree(resolved, target, include=inc)
            if n == 0:
                raise RuntimeError(
                    f"no objects found under prefix {resolved!r}"
                    + (f" matching {inc}" if inc else "")
                )
            total_n += n
            total_b += b
            links.append((dest.rsplit("/", 1)[-1] or dest, dest))

        # .nojekyll so paths/underscores serve verbatim; landing index at root.
        open(os.path.join(repo_dir, ".nojekyll"), "w").close()
        with open(os.path.join(repo_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(_landing_html(landing_title, links))

        _run(["git", "add", "-A"], cwd=repo_dir, env=env)
        commit = _run(["git", "commit", "-q", "-m",
                       f"Publish {total_n} files across {len(prefixes)} bundle(s)"],
                      cwd=repo_dir, env=env, check=False)
        if commit.returncode != 0 and "nothing to commit" not in (commit.stdout + commit.stderr):
            raise RuntimeError(f"git commit failed: {(commit.stderr or commit.stdout).strip()[:500]}")
        _run(["git", "push", "-u", "origin", branch], cwd=repo_dir, env=env)
        sha = _run(["git", "rev-parse", "HEAD"], cwd=repo_dir, env=env).stdout.strip()

        _ensure_pages(repo, branch, token)
        pages_url = f"https://{owner}.github.io/{name}/index.html"
        return PublishResult(repo, branch, total_n, total_b, sha, pages_url)
    finally:
        shutil.rmtree(work, ignore_errors=True)

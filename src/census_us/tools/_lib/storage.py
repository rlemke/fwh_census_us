"""Backend-aware paths for census cache + outputs.

On the fleet (``AFL_STORAGE=s3`` / ``AFL_DATA_ROOT=s3://afl-cache``) census
artifacts — the ACS/TIGER download cache and the extract CSV / GeoJSON /
summary outputs — must land in the shared MinIO object store, not silo to each
runner's local disk. This thin wrapper over ``facetwork.runtime.storage`` makes
that automatic:

- ``cache_root()`` / ``output_root()`` resolve under ``AFL_DATA_ROOT`` (which is
  an ``s3://`` URI on the fleet), falling back to the previous local defaults
  (``$output_base/census-cache`` / ``census-output``) when it isn't remote.
  The legacy ``AFL_CENSUS_CACHE_DIR`` / ``AFL_CENSUS_OUTPUT_DIR`` overrides still
  win, for explicit local placement.
- ``open_write()`` stages text/binary on local disk (preserving ``newline=`` /
  encoding semantics the ``csv``/``json`` writers need) then finalizes the bytes
  onto the backend — object stores don't do partial writes, so we never stream
  a half-written object.
- ``open_read()`` / ``localize()`` pull a remote URI down to a real local file
  before any reader that needs a file path (``csv``, ``zipfile``, ``fiona``,
  ``pyshp``) touches it.

Local backend is a pass-through: ``open_write``/``open_read`` are plain ``open``
and ``localize`` returns the path unchanged, so terminal CLI use and tests are
unaffected.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from collections.abc import Iterator
from typing import IO

from facetwork.config import get_output_base
from facetwork.runtime import storage as _fws


def is_remote(path: str) -> bool:
    return "://" in (path or "")


def _data_root() -> str:
    # AFL_DATA_ROOT (an s3:// URI on the fleet) wins; else the local output base.
    return os.environ.get("AFL_DATA_ROOT") or get_output_base()


def join(*parts: str) -> str:
    """POSIX-style join that is safe for ``s3://`` URIs (os.path.join is not)."""
    parts = [p for p in parts if p]
    if not parts:
        return ""
    base = parts[0].rstrip("/")
    rest = [p.strip("/") for p in parts[1:]]
    return "/".join([base, *[p for p in rest if p]])


def cache_root() -> str:
    ov = os.environ.get("AFL_CENSUS_CACHE_DIR")
    if ov:
        return ov
    r = _data_root()
    return join(r, "cache", "census-us", "cache") if is_remote(r) else join(r, "census-cache")


def output_root() -> str:
    ov = os.environ.get("AFL_CENSUS_OUTPUT_DIR")
    if ov:
        return ov
    r = _data_root()
    return join(r, "cache", "census-us", "output") if is_remote(r) else join(r, "census-output")


def exists(path: str) -> bool:
    return _fws.get_storage_backend(path).exists(path)


def size(path: str) -> int:
    return _fws.get_storage_backend(path).getsize(path)


def localize(path: str) -> str:
    """Remote URI → a local file path; no-op for local paths."""
    if not is_remote(path):
        return path
    return _fws.localize(path)


def open_read(path: str, mode: str = "r", **kw) -> IO:
    """Open ``path`` for reading, localizing a remote URI to disk first."""
    return open(localize(path), mode, **kw)


@contextlib.contextmanager
def open_write(path: str, mode: str = "w", **kw) -> Iterator[IO]:
    """Context manager that writes ``path`` on the active backend.

    Local: makedirs + plain open. Remote: stage to a local temp file (so the
    caller's ``newline=``/encoding and the csv/json writers behave exactly as on
    local disk), then push the finished bytes to the object store on close.
    """
    if not is_remote(path):
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        f = open(path, mode, **kw)
        try:
            yield f
        finally:
            f.close()
        return

    fd, tmp = tempfile.mkstemp(suffix="_" + os.path.basename(path))
    os.close(fd)
    f = open(tmp, mode, **kw)
    try:
        yield f
        f.close()
        with open(tmp, "rb") as src, _fws.get_storage_backend(path).open(path, "wb") as dst:
            dst.write(src.read())
    finally:
        if not f.closed:
            f.close()
        try:
            os.unlink(tmp)
        except OSError:
            pass

"""Tests conftest for the census-us repo.

Imports resolve via the editable install of ``census_us``; no
``sys.path`` manipulation needed.
"""

from __future__ import annotations

# ⚠️ Point every storage root at a temp dir for the whole session.
#
# `_data_root()` falls back to the machine's configured output base, which on
# the development hosts is /Volumes/afl_data — a macOS external volume. On any
# other machine that is unwritable, and 43 tests died with PermissionError:
# '/Volumes' the first time this suite ran on Linux CI. Tests should not write
# to a real data root in any case: a passing suite that mutates the operator's
# cache is a side effect nobody asked for.
import os
import tempfile

import pytest


@pytest.fixture(autouse=True, scope="session")
def _isolate_storage_roots():
    tmp = tempfile.mkdtemp(prefix="census-us-tests-")
    keys = ("FW_DATA_ROOT", "FW_OUTPUT_BASE", "FW_CENSUS_CACHE_DIR")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ["FW_DATA_ROOT"] = tmp
    os.environ["FW_OUTPUT_BASE"] = tmp
    os.environ["FW_CENSUS_CACHE_DIR"] = os.path.join(tmp, "cache")
    yield tmp
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
